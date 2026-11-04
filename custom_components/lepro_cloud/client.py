"""Lepro Cloud REST API and MQTT transport."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import ssl
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import paho.mqtt.client as mqtt
from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .catalog import PRODUCT_CONFIGS
from .const import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_LANGUAGE,
    DOMAIN,
    REGION_DISCOVERY_HOST,
    REGIONS,
)
from .device import device_name, is_supported_device, preserve_device_name
from .mqtt_key import MqttKeyError, load_mqtt_private_key
from .protocol import (
    DP_ONLINE,
    infer_report,
    make_get_payload,
    make_set_payload,
    state_datapoints_for_series,
    subscription_topics,
    topic_get,
    topic_set,
)
from .scenes import effect_family, merge_scenes, selected_effect

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20
MQTT_KEEPALIVE = 20


class LeproError(Exception):
    """Base class for Lepro integration errors."""


class LeproAuthError(LeproError):
    """Authentication failed."""


class LeproApiError(LeproError):
    """Lepro cloud API request failed."""


class LeproResponseError(LeproApiError):
    """Lepro cloud returned an application-level error."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class LeproMqttError(LeproError):
    """Lepro MQTT setup or publishing failed."""


def _now_seconds() -> int:
    return int(time.time())


def _persistent_mac(account: str) -> str:
    """Return a stable, locally-administered device address for an account."""
    digest = hashlib.sha256(account.strip().lower().encode()).hexdigest()
    return f"02:{digest[0:2]}:{digest[2:4]}:{digest[4:6]}:{digest[6:8]}:{digest[8:10]}"


class LeproApi:
    """Minimal Lepro Cloud API client."""

    def __init__(
        self, hass: HomeAssistant, region: str | None = None, *, host: str | None = None
    ) -> None:
        self._hass = hass
        self._session = async_get_clientsession(hass)
        self._host = host or REGIONS[region]
        self.token: str | None = None
        self.uid: str | None = None
        self.secret: str | None = None

    @classmethod
    async def async_resolve_region(cls, hass: HomeAssistant, username: str) -> str:
        """Resolve the account's regional API host using Lepro's bootstrap API."""
        bootstrap = cls(hass, host=REGION_DISCOVERY_HOST)
        region_info = await bootstrap._request(
            "POST",
            "/user/region",
            {"account": username, "timestamp": str(_now_seconds())},
        )
        api_host = str(region_info.get("apiHost") or "")
        for region, host in REGIONS.items():
            if host == api_host:
                return region
        raise LeproResponseError("Lepro returned an unknown account region")

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
        self,
        method: str,
        path: str,
        data: Mapping[str, Any] | None = None,
        *,
        _redirected: bool = False,
        json_body: bool = False,
    ) -> dict[str, Any]:
        url = f"https://{self._host}{path}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.request(
                    method,
                    url,
                    **({"json": data} if json_body else {"data": data}),
                    headers=self._headers(),
                )
                try:
                    payload = await response.json(content_type=None)
                except ValueError:
                    if response.status == 401:
                        raise LeproAuthError("Lepro authentication expired") from None
                    raise
                if response.status == 401:
                    raise LeproAuthError("Lepro authentication expired")
        except TimeoutError as err:
            raise LeproApiError("Timed out connecting to Lepro Cloud") from err
        except (ClientError, OSError, ValueError) as err:
            raise LeproApiError("Lepro Cloud is unavailable") from err

        if not isinstance(payload, dict):
            raise LeproApiError("Lepro Cloud returned an invalid response")

        try:
            code = int(payload["code"])
        except (KeyError, TypeError, ValueError) as err:
            raise LeproResponseError("Lepro response has no valid status code") from err
        if code == -100 and not _redirected:
            region = payload.get("data")
            host = region.get("apiHost") if isinstance(region, dict) else None
            if host not in REGIONS.values():
                raise LeproResponseError("Lepro returned an unknown account region")
            self._host = host
            return await self._request(
                method, path, data, _redirected=True, json_body=json_body
            )
        if response.status == 401 or code in (
            -202,
            -203,
            -204,
            -205,
            -900,
            401,
            1001,
            1002,
        ):
            raise LeproAuthError(
                "Lepro authentication expired or credentials were rejected"
            )
        if response.status >= 500:
            raise LeproApiError(f"Lepro Cloud API error (HTTP {response.status})")
        if response.status >= 400 or code != 0:
            raise LeproResponseError(
                f"Lepro Cloud rejected the request (code {code})", code=code
            )

        data_value = payload.get("data")
        if not isinstance(data_value, (dict, list)):
            raise LeproResponseError("Lepro response has no valid data")
        return (
            data_value if isinstance(data_value, dict) else {"list": data_value or []}
        )

    async def async_login(self, username: str, password: str) -> None:
        """Authenticate with Lepro Cloud."""
        identity = _persistent_mac(username)
        if getattr(self, "_hass", None) is not None:
            from homeassistant.helpers.instance_id import async_get

            # Android's mac field is an installation identifier, not a NIC MAC.
            identity = hashlib.sha256(
                (await async_get(self._hass)).encode()
            ).hexdigest()[:16]
        login = await self._request(
            "POST",
            "/user/login",
            {
                "platform": "2",
                "account": username,
                "password": password,
                "mac": identity,
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
        """Discover supported Wi-Fi lights and plugs across account families."""
        families = await self._request(
            "GET", f"/family/list/timestamp/{_now_seconds()}"
        )
        devices: dict[str, dict[str, Any]] = {}
        for family in _as_list(families):
            fid = family.get("fid")
            if not fid:
                continue
            result = await self._request(
                "GET", f"/v3/device/list/fid/{fid}/timestamp/{_now_seconds()}"
            )
            for device in _as_list(result):
                did = device.get("did")
                if did:
                    # The app's scene endpoint requires the owning family ID.
                    # Discovery responses do not reliably repeat it on every
                    # device record, so retain it while it is unambiguous.
                    device.setdefault("fid", fid)
                    key = str(did)
                    if key in devices:
                        device["scenes"] = merge_scenes(
                            devices[key].get("scenes", []), device.get("scenes", [])
                        )
                    devices[key] = device
        return list(devices.values())

    async def async_device_scenes(
        self, device: Mapping[str, Any], cursor: int = 0
    ) -> list[dict[str, Any]]:
        """Return the saved and supplied scenes for one device.

        This is the same per-device scene-list route used by the Android app.
        Scene payloads are intentionally returned unmodified: multipart RGBIC
        data is device-specific and must never be reconstructed by HA.
        """
        fid = device.get("fid")
        did = device.get("did")
        if not fid or not did:
            return []
        result = await self._request(
            "GET",
            f"/v3/scene/list/fid/{fid}/did/{did}/cid/{cursor}/limit/6/"
            f"timestamp/{_now_seconds()}",
        )
        return _as_list(result)

    async def async_product_configs(self) -> list[dict[str, Any]]:
        """Download the app's public product-to-effect mapping."""
        url = f"https://{self._host}/pub/resources/config.series.json"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.get(url, headers={})
                payload = await response.json(content_type=None)
        except (ClientError, OSError, TimeoutError, ValueError) as err:
            raise LeproApiError(
                "Unable to download Lepro product configuration"
            ) from err
        if response.status >= 400:
            raise LeproApiError("Unable to download Lepro product configuration")
        if not isinstance(payload, list):
            raise LeproApiError("Lepro product configuration is invalid")
        return [item for item in payload if isinstance(item, dict)]

    async def async_text(self, url: str) -> str:
        """Download certificates, authenticating only the active HTTPS API origin."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                for _ in range(6):
                    parsed = urlsplit(url)
                    trusted = (
                        parsed.scheme == "https"
                        and parsed.hostname == self._host
                        and parsed.port in (None, 443)
                        and parsed.username is None
                        and parsed.password is None
                    )
                    response = await self._session.get(
                        url,
                        headers=self._headers() if trusted else {},
                        allow_redirects=False,
                    )
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        response.release()
                        if not location:
                            raise LeproApiError("Lepro certificate redirect is invalid")
                        url = urljoin(url, location)
                        if urlsplit(url).scheme not in ("http", "https"):
                            raise LeproApiError("Lepro certificate redirect is invalid")
                        continue
                    if response.status >= 400:
                        raise LeproApiError("Lepro certificate download failed")
                    return await response.text()
                raise LeproApiError("Lepro certificate redirect limit exceeded")
        except (ClientError, OSError, TimeoutError, ValueError):
            raise LeproApiError("Unable to download Lepro MQTT certificate") from None


_PENDING_APIS = f"{DOMAIN}_pending_apis"


def cache_authenticated_api(
    hass: HomeAssistant, account_id: str, api: LeproApi, *, replace: bool = True
) -> None:
    """Keep a just-authenticated API session for the first entry setup."""
    pending = hass.data.setdefault(_PENDING_APIS, {})
    if replace:
        pending[account_id] = api
    else:
        pending.setdefault(account_id, api)


def take_authenticated_api(hass: HomeAssistant, account_id: str) -> LeproApi | None:
    """Consume a config-flow API session, if this is its first entry setup."""
    return hass.data.get(_PENDING_APIS, {}).pop(account_id, None)


def _as_list(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("list", payload)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise LeproResponseError("Lepro returned an invalid list")
    return value


class LeproCoordinator:
    """Coordinates Lepro REST discovery and MQTT state for one config entry."""

    def __init__(
        self, hass: HomeAssistant, entry: Any, api: LeproApi | None = None
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.api = api or LeproApi(hass, entry.data["region"])
        self.devices: dict[str, dict[str, Any]] = {}
        self.effect_types: dict[str, str] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.listeners: set[Callable[[str], None]] = set()
        self.client: mqtt.Client | None = None
        self.tmp: tempfile.TemporaryDirectory[str] | None = None
        self.connected = False
        self._stopping = False
        self._maintenance_task: asyncio.Task[None] | None = None
        self._refresh_requested = asyncio.Event()
        self._profile_signature = ""
        self._mqtt_secret: str | None = None
        self._last_refresh = 0.0
        self._scene_cache: dict[str, list[dict[str, Any]]] = {}
        self._reauth_requested = False
        self._fresh: set[str] = set()
        self._pending_commands: dict[int, tuple[str, float]] = {}
        self._command_lock = threading.Lock()
        self._command_timers: set[asyncio.TimerHandle] = set()
        self._initial_state_timer: asyncio.TimerHandle | None = None
        self._state_query_retries = 0
        self._property_messages = 0
        self._accepted_reports = 0

    async def async_start(self) -> None:
        """Authenticate, discover devices, and start MQTT."""
        if self.entry.data.get("auth_implementation") == DOMAIN:
            await self.api.async_restore_session()
        elif not self.api.token or not self.api.secret:
            await self.api.async_login(
                self.entry.data["username"], self.entry.data["password"]
            )
        tasks = [
            asyncio.create_task(self.api.async_profile()),
            asyncio.create_task(self.api.async_devices()),
        ]
        try:
            profile, devices = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        self.devices = {
            str(device["did"]): device
            for device in devices
            if device.get("did") and is_supported_device(device)
        }
        await self._load_product_configs()
        await self._load_device_scenes()
        info = _mqtt_info(profile)
        try:
            key = await self.hass.async_add_executor_job(load_mqtt_private_key)
        except MqttKeyError as err:
            raise LeproMqttError(str(err)) from err
        certs = await self._resolve_certs(info, key, self.api.secret or "")
        await self._async_start_mqtt(info, certs)
        self._profile_signature = self._signature(info, certs)
        self._mqtt_secret = self.api.secret
        self._maintenance_task = self.hass.async_create_background_task(
            self._maintain_session(), "Lepro Cloud refresh"
        )

    async def _load_product_configs(self) -> bool:
        """Refresh reviewed capabilities; preserve the last good remote data."""
        before = {
            did: (device.get("_color_picker"), effect_family(device, self.effect_types))
            for did, device in self.devices.items()
        }
        configs = [
            dict(item) for item in getattr(self, "_product_configs", PRODUCT_CONFIGS)
        ]
        try:
            remote_configs = await self.api.async_product_configs()
        except LeproApiError as err:
            _LOGGER.debug("Unable to load Lepro effect configuration: %s", err)
        else:
            merged = {str(item["series"]).upper(): item for item in configs}
            for item in remote_configs:
                if item.get("series"):
                    series = str(item["series"]).upper()
                    merged.setdefault(series, {}).update(item)
            configs = list(merged.values())
        self._product_configs = configs
        self.effect_types = {
            str(item["series"]).upper(): str(item["effect"])
            for item in configs
            if item.get("series")
        }
        for device in self.devices.values():
            config = next(
                (
                    item
                    for item in configs
                    if str(item.get("series", "")).upper()
                    == str(device.get("series", "")).upper()
                ),
                {},
            )
            device["_color_picker"] = config.get("colorPicker")
        return any(
            before[did]
            != (device.get("_color_picker"), effect_family(device, self.effect_types))
            for did, device in self.devices.items()
        )

    @staticmethod
    def _signature(info: Mapping[str, Any], certs: Mapping[str, str]) -> str:
        return hashlib.sha256(
            json.dumps(
                [
                    str(info["host"]),
                    int(info["port"]),
                    {key: value.strip() for key, value in certs.items()},
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()

    async def _async_start_mqtt(
        self, info: Mapping[str, Any], certs: Mapping[str, str]
    ) -> None:
        task = asyncio.ensure_future(
            self.hass.async_add_executor_job(self._start_mqtt, info, certs)
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # A cancelled executor await does not stop its worker. Collect it first.
            await asyncio.gather(task, return_exceptions=True)
            await self._stop_transport()
            raise

    async def _maintain_session(self) -> None:
        """Refresh existing credentials; revoked login always requires reauth.

        Five minutes is an integration refresh policy, not an APK token lifetime.
        Failure backoff is bounded, and never performs an automatic password login.
        """
        delay = 300
        while not self._stopping and not self._reauth_requested:
            try:
                await asyncio.wait_for(self._refresh_requested.wait(), timeout=delay)
            except TimeoutError:
                pass
            self._refresh_requested.clear()
            await asyncio.sleep(max(0, 30 - (time.monotonic() - self._last_refresh)))
            self._last_refresh = time.monotonic()
            try:
                await self._refresh_session()
                delay = 300
            except LeproAuthError:
                await self._require_reauth()
                return
            except (LeproError, MqttKeyError, OSError, ValueError):
                delay = min(300, max(30, delay * 2))
                _LOGGER.debug("Lepro refresh failed; retrying with bounded backoff")

    async def _require_reauth(self) -> None:
        if self._reauth_requested or self._stopping:
            return
        self._reauth_requested = True
        task = self._maintenance_task
        try:
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                # A previously failed background task must not prevent the prompt.
                await asyncio.gather(task, return_exceptions=True)
            await self._stop_transport()
        finally:
            if self._maintenance_task is task:
                self._maintenance_task = None
            if not self._stopping:
                self.entry.async_start_reauth(self.hass)

    def _schedule_reload(self) -> None:
        cache_authenticated_api(self.hass, self.entry.unique_id, self.api)
        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    async def _refresh_session(self) -> None:
        profile = await self.api.async_profile()
        devices = await self.api.async_devices()
        discovered = {
            str(d["did"]): d for d in devices if d.get("did") and is_supported_device(d)
        }
        if discovered.keys() != self.devices.keys() or any(
            self.devices[did].get(key) != device.get(key)
            for did, device in discovered.items()
            if did in self.devices
            for key in (
                "name",
                "friendlyName",
                "nickname",
                "deviceName",
                "devName",
                "fwVersion",
                "hwVersion",
                "series",
                "control",
                "effect",
                "fid",
                "type",
                "deviceType",
                "devType",
                "pid",
                "mac",
                "deviceSn",
            )
        ):
            self._schedule_reload()
            return
        for did, device in discovered.items():
            # Preserve the dict referenced by entities; replace the source scenes.
            old = self.devices[did]
            picker = old.get("_color_picker")
            previous_name = device_name(old)
            native_temperature = old.get("_native_color_temp", False)
            old.clear()
            old.update(device)
            old["_color_picker"] = picker
            old["_native_color_temp"] = native_temperature
            preserve_device_name(old, previous_name)
        if await self._load_product_configs():
            self._schedule_reload()
            return
        await self._load_device_scenes()
        info = _mqtt_info(profile)
        key = await self.hass.async_add_executor_job(load_mqtt_private_key)
        certs = await self._resolve_certs(info, key, self.api.secret or "")
        signature = self._signature(info, certs)
        if (
            not self.connected
            or signature != self._profile_signature
            or self._mqtt_secret != self.api.secret
        ):
            await self._stop_transport()
            await self._async_start_mqtt(info, certs)
            self._profile_signature = signature
            self._mqtt_secret = self.api.secret
        self._notify_all()

    async def _load_device_scenes(self) -> None:
        """Load app scenes without making device discovery unavailable."""
        device_items = list(self.devices.items())
        results = await asyncio.gather(
            *(self._async_device_scenes(device) for _, device in device_items),
            return_exceptions=True,
        )
        for (did, device), result in zip(device_items, results, strict=True):
            if isinstance(result, LeproAuthError):
                raise result
            if isinstance(result, Exception):
                _LOGGER.debug("Unable to load Lepro scenes for %s: %s", did, result)
                result = getattr(self, "_scene_cache", {}).get(did, [])
            elif hasattr(self, "_scene_cache"):
                self._scene_cache[did] = result
            embedded = device.get("scenes")
            device["scenes"] = merge_scenes(
                embedded if isinstance(embedded, list) else [], result
            )

    async def _async_device_scenes(
        self, device: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Collect every page of device saved scenes using the app cursor."""
        async with asyncio.timeout(120):
            return await self._collect_scene_pages(device)

    async def _collect_scene_pages(
        self, device: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        scenes: list[dict[str, Any]] = []
        cursor = 0
        for _ in range(10000):
            page = await self.api.async_device_scenes(device, cursor=cursor)
            if not page:
                break
            scenes = merge_scenes(scenes, page)
            cursors = [
                int(scene["cid"])
                for scene in page
                if isinstance(scene.get("cid"), int | str)
                and str(scene["cid"]).isdigit()
            ]
            next_cursor = max(cursors, default=cursor)
            if next_cursor <= cursor:
                break
            cursor = next_cursor
        else:
            raise LeproResponseError(
                "Lepro scene pagination exceeded its safety budget"
            )
        return scenes

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
            raise LeproMqttError(
                "Lepro MQTT profile did not provide PEM certificate data"
            )
        return value

    def _start_mqtt(self, info: Mapping[str, Any], certs: Mapping[str, str]) -> None:
        """Configure MQTT without blocking Home Assistant startup.

        ``connect_async`` leaves the first connection and later reconnects to
        Paho's network loop. A temporary broker outage must make entities
        unavailable, rather than repeatedly restart discovery and login.
        """
        tmp = tempfile.TemporaryDirectory(prefix="lepro_cloud_")
        client: mqtt.Client | None = None
        loop_started = False
        try:
            directory = Path(tmp.name)
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
                # The Android app uses the login secret in its client ID.
                client_id=f"lepro-app-{self.api.secret}",
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
            client.on_connect_fail = self._on_connect_fail
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            client.on_subscribe = self._on_subscribe
            client.connect_async(str(info["host"]), int(info["port"]), MQTT_KEEPALIVE)
            self.client = client
            self.tmp = tmp
            loop_result = client.loop_start()
            if loop_result not in (None, mqtt.MQTT_ERR_SUCCESS):
                raise LeproMqttError("Lepro MQTT network loop could not start")
            loop_started = True
        except Exception as err:
            self.client = None
            self.tmp = None
            if client is not None:
                if loop_started:
                    with suppress(Exception):
                        client.loop_stop()
                with suppress(Exception):
                    client.disconnect()
            tmp.cleanup()
            if isinstance(err, LeproMqttError):
                raise
            raise LeproMqttError("Unable to connect to Lepro MQTT") from err

        self.tmp = tmp
        self.client = client

    def _on_connect_fail(self, _client: mqtt.Client, _userdata: Any) -> None:
        """Expose an unavailable transport while Paho keeps retrying."""
        self.hass.loop.call_soon_threadsafe(self._set_transport_state, _client, False)
        self._request_refresh()
        _LOGGER.debug("Lepro MQTT connection attempt failed; Paho will reconnect")

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if self._stopping or (
            getattr(self, "client", None) is not None and client is not self.client
        ):
            return
        if _reason_failed(reason_code):
            self._request_refresh()
            _LOGGER.warning("Lepro MQTT connection failed: %s", reason_code)
            self.hass.loop.call_soon_threadsafe(
                self._set_transport_state, client, False
            )
            return
        self.hass.loop.call_soon_threadsafe(self._set_transport_state, client, True)
        for did, device in self.devices.items():
            for topic in subscription_topics(did):
                self._check_subscription(client.subscribe(topic, qos=0))
            series = device.get("series") or device.get("pid")
            family = effect_family(device, getattr(self, "effect_types", {}))
            scene_datapoints = tuple(
                dict.fromkeys(
                    selected[0]
                    for scene in device.get("scenes", [])
                    if isinstance(scene, dict)
                    and (selected := selected_effect(scene, family)) is not None
                )
            )
            if "d50" in scene_datapoints:
                scene_datapoints += ("d52",)
            result = client.publish(
                topic_get(did),
                json.dumps(
                    make_get_payload(
                        state_datapoints_for_series(series, scene_datapoints)
                    )
                ),
                qos=0,
            )
            if result is not None and result.rc != mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.warning("Lepro MQTT initial state query failed")
                self.hass.loop.call_soon_threadsafe(
                    self._set_transport_state, client, False
                )
                self._request_refresh()
        secret = getattr(getattr(self, "api", None), "secret", None)
        if secret:
            self._check_subscription(
                client.subscribe(f"le/{secret}/act/app/exe", qos=0)
            )

    def _check_subscription(self, result: Any) -> None:
        if result is not None and result[0] != mqtt.MQTT_ERR_SUCCESS:
            _LOGGER.warning("Lepro MQTT subscription failed")
            self.hass.loop.call_soon_threadsafe(
                self._set_transport_state, self.client, False
            )
            self._request_refresh()

    def _on_subscribe(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _mid: int,
        reason_codes: list[Any],
        _properties: Any,
    ) -> None:
        if self._stopping or client is not self.client:
            return
        if any(_reason_failed(code) for code in reason_codes):
            _LOGGER.warning("Lepro broker rejected a subscription")
            self.hass.loop.call_soon_threadsafe(
                self._set_transport_state, client, False
            )
            self._request_refresh()

    def _request_refresh(self) -> None:
        if hasattr(self, "_refresh_requested"):
            self.hass.loop.call_soon_threadsafe(self._refresh_requested.set)

    def _cancel_initial_state_retry(self) -> None:
        handle = getattr(self, "_initial_state_timer", None)
        if handle:
            handle.cancel()
        self._initial_state_timer = None

    def _retry_missing_state(self, client: mqtt.Client, attempt: int) -> None:
        """Retry missed startup GET replies twice, without changing device state."""
        if self._stopping or client is not self.client or not self.connected:
            return
        self._initial_state_timer = None
        missing = self.devices.keys() - self._fresh
        if not missing:
            return
        self._state_query_retries += 1
        _LOGGER.debug(
            "Retrying initial Lepro state queries for %s devices", len(missing)
        )
        for did in missing:
            self._query_device(did)
        if attempt < 2:
            self._initial_state_timer = self.hass.loop.call_later(
                REQUEST_TIMEOUT, self._retry_missing_state, client, attempt + 1
            )

    def _set_transport_state(self, client: mqtt.Client, connected: bool) -> None:
        """Serialize connection state and freshness with HA entity reads."""
        if self._stopping or client is not getattr(self, "client", None):
            return
        self._cancel_initial_state_retry()
        if connected:
            self._fresh = set()
            for state in self.states.values():
                state.pop(DP_ONLINE, None)
            if self.devices:
                self._initial_state_timer = self.hass.loop.call_later(
                    REQUEST_TIMEOUT, self._retry_missing_state, client, 1
                )
        self.connected = connected
        self._notify_all()

    def device_available(self, did: str) -> bool:
        return (
            self.connected
            and did in self._fresh
            and str(self.states.get(did, {}).get(DP_ONLINE, 0)) == "1"
        )

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if getattr(self, "client", None) is not None and _client is not self.client:
            return
        self.hass.loop.call_soon_threadsafe(self._set_transport_state, _client, False)
        if not self._stopping and _reason_failed(reason_code):
            _LOGGER.debug(
                "Lepro MQTT disconnected; paho will reconnect: %s", reason_code
            )

    def _on_message(
        self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage
    ) -> None:
        if self._stopping or (
            getattr(self, "client", None) is not None and _client is not self.client
        ):
            return
        try:
            parts = message.topic.split("/")
            payload = json.loads(message.payload.decode())
            if not isinstance(payload, dict):
                return
            secret = getattr(getattr(self, "api", None), "secret", None)
            if secret and message.topic == f"le/{secret}/act/app/exe":
                action = payload.get("d")
                if isinstance(action, dict):
                    self.hass.loop.call_soon_threadsafe(
                        self._account_action, action.get("action")
                    )
                return
            if len(parts) < 4 or parts[0] != "le" or parts[2] != "prp":
                return
            did = parts[1]
            if did not in self.devices or message.topic not in subscription_topics(did):
                return
            self.hass.loop.call_soon_threadsafe(self._record_property_message)
            # APK MqttConnectionPool dispatches d-bearing messages as state,
            # regardless of c. Only c-only envelopes are command responses.
            if "d" not in payload:
                if "c" in payload:
                    self.hass.loop.call_soon_threadsafe(
                        self._command_response, did, payload.get("id"), payload["c"]
                    )
                return
            state = payload["d"]
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            _LOGGER.debug("Ignoring malformed Lepro MQTT message")
            return
        if isinstance(state, dict):
            clean = _validated_state(state)
            if clean:
                clean = infer_report(
                    clean, get_response=parts[-1] == "getr" and did.isdigit()
                )
                self.hass.loop.call_soon_threadsafe(self._apply_report, did, clean)

    def _account_action(self, action: Any) -> None:
        if self._stopping:
            return
        if action == "logout":
            self.hass.async_create_task(self._require_reauth())
        elif action == "disDevice":
            self._request_refresh()

    def _command_response(self, did: str, identifier: Any, code: Any) -> None:
        try:
            identifier = int(identifier)
        except (ValueError, TypeError):
            return
        with self._command_lock:
            pending = self._pending_commands.get(identifier)
            if pending is None or pending[0] != did:
                return
            self._pending_commands.pop(identifier)
        if str(code) != "0":
            _LOGGER.warning("Lepro device rejected a command")
            self._query_device(did)

    def _query_device(self, did: str) -> None:
        if self.client and self.connected and did in self.devices:
            series = self.devices[did].get("series")
            self.client.publish(
                topic_get(did),
                json.dumps(make_get_payload(state_datapoints_for_series(series))),
                qos=0,
            )

    def _expire_command(self, identifier: int) -> None:
        with self._command_lock:
            pending = self._pending_commands.pop(identifier, None)
        if pending is not None and not self._stopping:
            # ack=0 can legitimately omit setr; request authoritative state.
            self._query_device(pending[0])

    def _schedule_command_timeout(self, identifier: int) -> None:
        if self._stopping:
            return
        handle = None

        def expire() -> None:
            self._command_timers.discard(handle)
            self._expire_command(identifier)

        handle = self.hass.loop.call_later(10, expire)
        self._command_timers.add(handle)

    def _record_property_message(self) -> None:
        if not self._stopping:
            self._property_messages = getattr(self, "_property_messages", 0) + 1

    def _apply_report(self, did: str, state: dict[str, Any]) -> None:
        """Apply a broker report on Home Assistant's event loop."""
        if self._stopping:
            return
        self.states.setdefault(did, {}).update(state)
        if not hasattr(self, "_fresh"):
            self._fresh = set()
        self._fresh.add(did)
        self._accepted_reports = getattr(self, "_accepted_reports", 0) + 1
        if self.devices.keys() <= self._fresh:
            self._cancel_initial_state_retry()
        self._notify(did)

    def _schedule_device_updates(self) -> None:
        """Schedule availability updates from the MQTT callback thread."""
        self.hass.loop.call_soon_threadsafe(self._notify_all)

    def _notify_all(self) -> None:
        """Notify every device listener after a transport state change."""
        for did in self.devices:
            self._notify(did)

    def _notify(self, did: str) -> None:
        for listener in tuple(self.listeners):
            listener(did)

    def command(self, did: str, values: Mapping[str, Any]) -> None:
        """Publish a state command."""
        if not self.client or not self.connected or self._stopping:
            raise LeproMqttError("Lepro MQTT client is not started")
        if did not in self.devices:
            raise LeproMqttError("Unknown Lepro device")
        payload = make_set_payload(values)
        with self._command_lock:
            while payload["id"] in self._pending_commands:
                payload = make_set_payload(values)
            if len(self._pending_commands) >= 1000:
                raise LeproMqttError("Too many pending Lepro commands")
            self._pending_commands[payload["id"]] = (did, time.monotonic())
        message = json.dumps(payload, separators=(",", ":"))
        try:
            result = self.client.publish(topic_set(did), message, qos=0)
        except Exception as err:
            with self._command_lock:
                self._pending_commands.pop(payload["id"], None)
            raise LeproMqttError("Lepro MQTT command could not be queued") from err
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            with self._command_lock:
                self._pending_commands.pop(payload["id"], None)
            raise LeproMqttError(f"Lepro MQTT publish failed with code {result.rc}")
        self.hass.loop.call_soon_threadsafe(
            self._schedule_command_timeout, payload["id"]
        )

    def listen(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Register a state listener."""
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    async def async_stop(self) -> None:
        """Stop MQTT and clean up temporary certificate files."""
        self._stopping = True
        task = getattr(self, "_maintenance_task", None)
        try:
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        finally:
            self._maintenance_task = None
            await self._stop_transport()

    async def _stop_transport(self) -> None:
        """Release the old connection even when disconnect raises."""
        for handle in getattr(self, "_command_timers", set()):
            handle.cancel()
        self._command_timers = set()
        if hasattr(self, "_command_lock"):
            with self._command_lock:
                self._pending_commands.clear()
        self._cancel_initial_state_retry()
        self._fresh = set()
        client = self.client
        self.client = None
        self.connected = False
        tmp = self.tmp
        self.tmp = None
        try:
            if client:
                try:
                    await self.hass.async_add_executor_job(client.disconnect)
                except OSError:
                    _LOGGER.debug("Lepro MQTT disconnect failed during cleanup")
                finally:
                    await self.hass.async_add_executor_job(client.loop_stop)
        finally:
            if tmp:
                await self.hass.async_add_executor_job(tmp.cleanup)
            if not self._stopping:
                self._notify_all()


def _validated_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Reject malformed values before APK-style inference."""
    result: dict[str, Any] = {}
    limits = {
        "online": 1,
        "d1": 1,
        "d2": 5,
        "d3": 1000,
        "d4": 1000,
        "d52": 1000,
        "d53": 100000,
        "d100": 2,
        "d102": 1,
        "d157": 1,
        "d172": 1,
    }
    for key, value in state.items():
        if key in limits:
            try:
                number = int(value)
                valid = (
                    str(value) in {str(number), "True", "False"}
                    and 0 <= number <= limits[key]
                )
            except (TypeError, ValueError, OverflowError):
                valid = False
            if valid:
                result[key] = number
            elif key == "online":
                return {}
        elif key == "d5":
            from .protocol import parse_lepro_hsv

            if parse_lepro_hsv(value) is not None:
                result[key] = value
        elif (
            key == "d101"
            and value in ("000000000", "100000000")
            or key in ("d6", "d50")
            and isinstance(value, str)
            and 0 < len(value) <= 65536
        ):
            result[key] = value
    return result


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
