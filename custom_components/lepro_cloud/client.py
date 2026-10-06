"""Clean-room Lepro Cloud REST API and MQTT transport."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import json
import logging
from pathlib import Path
import ssl
import tempfile
import time
from typing import Any

import paho.mqtt.client as mqtt

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import APP_NAME, APP_VERSION, DEFAULT_LANGUAGE, REGIONS
from .mqtt_key import MqttKeyError, load_mqtt_private_key
from .protocol import (
    make_get_payload,
    make_set_payload,
    subscription_topics,
    topic_get,
    topic_set,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20
MQTT_KEEPALIVE = 60


class LeproError(Exception):
    """Base class for Lepro integration errors."""


class LeproAuthError(LeproError):
    """Authentication failed."""


class LeproApiError(LeproError):
    """Lepro cloud API request failed."""


class LeproResponseError(LeproApiError):
    """Lepro cloud returned an application-level error."""


class LeproMqttError(LeproError):
    """Lepro MQTT setup or publishing failed."""


def _now_seconds() -> int:
    return int(time.time())


class LeproApi:
    """Minimal Lepro Cloud API client."""

    def __init__(self, hass: HomeAssistant, region: str) -> None:
        self._session = async_get_clientsession(hass)
        self._host = REGIONS[region]
        self.token: str | None = None
        self.uid: str | None = None
        self.secret: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "App-Name": APP_NAME,
            "App-Version": APP_VERSION,
            "Platform": "2",
            "Language": DEFAULT_LANGUAGE,
            "Slanguage": DEFAULT_LANGUAGE,
            "Timestamp": str(_now_seconds()),
            "User-Agent": f"LE/{APP_VERSION} (Home Assistant)",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["token"] = self.token
        return headers

    async def _request(
        self, method: str, path: str, data: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"https://{self._host}{path}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.request(
                    method,
                    url,
                    data=data,
                    headers=self._headers(),
                )
                payload = await response.json(content_type=None)
        except TimeoutError as err:
            raise LeproApiError("Timed out connecting to Lepro Cloud") from err
        except (OSError, ValueError) as err:
            raise LeproApiError("Lepro Cloud is unavailable") from err

        if not isinstance(payload, dict):
            raise LeproApiError("Lepro Cloud returned an invalid response")

        code = payload.get("code")
        if response.status in (401, 403) or code in (401, 403, 1001, 1002):
            raise LeproAuthError(str(payload.get("msg") or "Invalid Lepro credentials"))
        if response.status >= 500:
            raise LeproApiError(str(payload.get("msg") or "Lepro Cloud API error"))
        if response.status >= 400 or code not in (0, "0", None):
            raise LeproResponseError(str(payload.get("msg") or "Lepro Cloud API error"))

        data_value = payload.get("data")
        return data_value if isinstance(data_value, dict) else {"list": data_value or []}

    async def async_login(self, username: str, password: str) -> None:
        """Authenticate with Lepro Cloud."""
        login = await self._request(
            "POST",
            "/user/login",
            {
                "platform": "2",
                "account": username,
                "password": password,
                "mac": "00:00:00:00:00:00",
                "timestamp": str(_now_seconds()),
                "language": DEFAULT_LANGUAGE,
                "fcmToken": "",
            },
        )
        self.token = login.get("token")
        self.uid = login.get("uid")
        self.secret = login.get("secret")
        if not self.token or not self.secret:
            raise LeproAuthError("Lepro returned incomplete login credentials")

    async def async_profile(self) -> dict[str, Any]:
        """Fetch the user profile, including MQTT information."""
        return await self._request("GET", "/user/profile")

    async def async_devices(self) -> list[dict[str, Any]]:
        """Discover devices across all account families."""
        families = await self._request("GET", f"/family/list/timestamp/{_now_seconds()}")
        devices: list[dict[str, Any]] = []
        for family in _as_list(families):
            fid = family.get("fid")
            if not fid:
                continue
            result = await self._request(
                "GET", f"/v3/device/list/fid/{fid}/timestamp/{_now_seconds()}"
            )
            devices.extend(device for device in _as_list(result) if isinstance(device, dict))
        return devices

    async def async_text(self, url: str) -> str:
        """Download text content from a profile-provided URL."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.get(url, headers=self._headers())
                response.raise_for_status()
                return await response.text()
        except (OSError, TimeoutError, ValueError) as err:
            raise LeproApiError(f"Unable to download Lepro certificate from {url}") from err


def _as_list(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("list", payload)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


class LeproCoordinator:
    """Coordinates Lepro REST discovery and MQTT state for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        self.hass = hass
        self.entry = entry
        self.api = LeproApi(hass, entry.data["region"])
        self.devices: dict[str, dict[str, Any]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.listeners: set[Callable[[str], None]] = set()
        self.client: mqtt.Client | None = None
        self.tmp: tempfile.TemporaryDirectory[str] | None = None
        self.connected = False
        self._stopping = False

    async def async_start(self) -> None:
        """Authenticate, discover devices, and start MQTT."""
        await self.api.async_login(self.entry.data["username"], self.entry.data["password"])
        profile, devices = await asyncio.gather(
            self.api.async_profile(),
            self.api.async_devices(),
        )
        self.devices = {str(device["did"]): device for device in devices if device.get("did")}
        info = _mqtt_info(profile)
        try:
            key = load_mqtt_private_key()
        except MqttKeyError as err:
            raise LeproMqttError(str(err)) from err
        certs = await self._resolve_certs(info, key, self.api.secret or "")
        await self.hass.async_add_executor_job(self._connect, info, certs)

    async def _resolve_certs(
        self, info: Mapping[str, Any], key: str, key_password: str
    ) -> dict[str, str]:
        return {
            "root": await self._resolve_cert_text(str(info["root"])),
            "cert": await self._resolve_cert_text(str(info["cert"])),
            "key": key,
            "key_password": key_password,
        }

    async def _resolve_cert_text(self, value: str) -> str:
        if value.startswith(("http://", "https://")):
            value = await self.api.async_text(value)
        if "-----BEGIN" not in value:
            raise LeproMqttError("Lepro MQTT profile did not provide PEM certificate data")
        return value

    def _connect(self, info: Mapping[str, Any], certs: Mapping[str, str]) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="lepro_cloud_")
        directory = Path(self.tmp.name)
        paths = {
            "root": directory / "root.pem",
            "cert": directory / "cert.pem",
            "key": directory / "key.pem",
        }
        for name, path in paths.items():
            path.write_text(certs[name], encoding="utf-8")
            path.chmod(0o600)

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ha-lepro-{self.api.uid or _now_seconds()}",
            clean_session=True,
        )
        client.tls_set(
            ca_certs=str(paths["root"]),
            certfile=str(paths["cert"]),
            keyfile=str(paths["key"]),
            keyfile_password=certs["key_password"],
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.reconnect_delay_set(min_delay=2, max_delay=300)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect(str(info["host"]), int(info["port"]), MQTT_KEEPALIVE)
        client.loop_start()
        self.client = client

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if _reason_failed(reason_code):
            _LOGGER.warning("Lepro MQTT connection failed: %s", reason_code)
            self.connected = False
            return
        self.connected = True
        for did in self.devices:
            for topic in subscription_topics(did):
                client.subscribe(topic, qos=1)
            client.publish(topic_get(did), json.dumps(make_get_payload()), qos=1)

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        self.connected = False
        if not self._stopping and _reason_failed(reason_code):
            _LOGGER.debug("Lepro MQTT disconnected; paho will reconnect: %s", reason_code)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            parts = message.topic.split("/")
            if len(parts) < 4 or parts[0] != "le" or parts[2] != "prp":
                return
            did = parts[1]
            payload = json.loads(message.payload.decode())
            state = payload.get("d", {})
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            _LOGGER.debug("Ignoring malformed Lepro MQTT message on %s", message.topic)
            return
        if isinstance(state, dict):
            self.states.setdefault(did, {}).update(state)
            self.hass.loop.call_soon_threadsafe(self._notify, did)

    def _notify(self, did: str) -> None:
        for listener in tuple(self.listeners):
            listener(did)

    def command(self, did: str, values: Mapping[str, Any]) -> None:
        """Publish a state command."""
        if not self.client:
            raise LeproMqttError("Lepro MQTT client is not started")
        message = json.dumps(make_set_payload(values), separators=(",", ":"))
        result = self.client.publish(topic_set(did), message, qos=1)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise LeproMqttError(f"Lepro MQTT publish failed with code {result.rc}")

    def listen(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Register a state listener."""
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    async def async_stop(self) -> None:
        """Stop MQTT and clean up temporary certificate files."""
        self._stopping = True
        client = self.client
        self.client = None
        if client:
            await self.hass.async_add_executor_job(client.disconnect)
            await self.hass.async_add_executor_job(client.loop_stop)
        if self.tmp:
            self.tmp.cleanup()
            self.tmp = None


def _mqtt_info(profile: Mapping[str, Any]) -> dict[str, Any]:
    info = profile.get("mqtt")
    if not isinstance(info, dict):
        raise LeproMqttError("Lepro profile did not return MQTT credentials")
    if not all(info.get(key) for key in ("host", "port", "root", "cert")):
        raise LeproMqttError("Lepro profile returned incomplete MQTT credentials")
    return info


def _reason_failed(reason_code: Any) -> bool:
    """Return true when a paho reason code represents failure."""
    if hasattr(reason_code, "is_failure"):
        return bool(reason_code.is_failure)
    try:
        return int(reason_code) != 0
    except (TypeError, ValueError):
        return bool(reason_code)
