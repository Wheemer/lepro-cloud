"""Tests for Lepro REST request timestamps."""

from __future__ import annotations

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types
from typing import Any


def _install_client_import_stubs() -> None:
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    homeassistant_core = types.ModuleType("homeassistant.core")
    homeassistant_core.HomeAssistant = object
    homeassistant_const = types.ModuleType("homeassistant.const")
    homeassistant_const.Platform = types.SimpleNamespace(LIGHT="light", SWITCH="switch")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None

    paho = types.ModuleType("paho")
    paho_mqtt = types.ModuleType("paho.mqtt")
    paho_mqtt_client = types.ModuleType("paho.mqtt.client")
    paho_mqtt_client.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
    paho_mqtt_client.MQTT_ERR_SUCCESS = 0
    paho_mqtt_client.Client = object
    paho_mqtt_client.ConnectFlags = object
    paho_mqtt_client.DisconnectFlags = object
    paho_mqtt_client.MQTTMessage = object
    paho_mqtt_client.Properties = object
    paho_mqtt_client.ReasonCode = object

    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules["homeassistant.core"] = homeassistant_core
    sys.modules["homeassistant.const"] = homeassistant_const
    sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client
    sys.modules.setdefault("paho", paho)
    sys.modules["paho.mqtt"] = paho_mqtt
    sys.modules["paho.mqtt.client"] = paho_mqtt_client


def _load_client_module() -> Any:
    _install_client_import_stubs()
    package = types.ModuleType("custom_components.lepro_cloud")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "lepro_cloud")]
    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    sys.modules["custom_components.lepro_cloud"] = package
    client_path = Path(package.__path__[0]) / "client.py"
    spec = spec_from_file_location("custom_components.lepro_cloud.client", client_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    async def json(self, **_kwargs: Any) -> Any:
        return self._payload

    async def text(self) -> str:
        return str(self._payload)


class RecordingSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.requests.append(
            {"method": method, "url": url, "data": data, "headers": headers}
        )
        return self.responses.pop(0)

    async def get(
        self, url: str, headers: dict[str, str] | None = None
    ) -> FakeResponse:
        self.requests.append(
            {"method": "GET", "url": url, "data": None, "headers": headers}
        )
        return self.responses.pop(0)


def _api(client_module: Any, session: RecordingSession) -> Any:
    api = client_module.LeproApi.__new__(client_module.LeproApi)
    api._session = session
    api._host = "api.example.invalid"
    api.token = None
    api.uid = None
    api.secret = None
    return api


def test_login_body_and_headers_use_unix_seconds(monkeypatch: Any) -> None:
    client_module = _load_client_module()
    monkeypatch.setattr(client_module.time, "time", lambda: 1720000000.789)
    session = RecordingSession(
        [
            FakeResponse(
                {
                    "code": 0,
                    "data": {"token": "token", "uid": "uid", "secret": "secret"},
                }
            )
        ]
    )
    api = _api(client_module, session)

    asyncio.run(api.async_login("fake@example.invalid", "fake-password"))

    request = session.requests[0]
    assert request["url"] == "https://api.example.invalid/user/login"
    assert request["data"]["timestamp"] == "1720000000"
    assert len(request["data"]["timestamp"]) == 10
    assert request["headers"]["Timestamp"] == "1720000000"
    assert len(request["headers"]["Timestamp"]) == 10


def test_discovery_urls_use_unix_seconds(monkeypatch: Any) -> None:
    client_module = _load_client_module()
    monkeypatch.setattr(client_module.time, "time", lambda: 1720000000.789)
    session = RecordingSession(
        [
            FakeResponse({"code": 0, "data": [{"fid": "family-1"}]}),
            FakeResponse({"code": 0, "data": [{"did": "device-1"}]}),
        ]
    )
    api = _api(client_module, session)

    assert asyncio.run(api.async_devices()) == [{"did": "device-1"}]

    assert session.requests[0]["url"].endswith("/family/list/timestamp/1720000000")
    assert session.requests[1]["url"].endswith(
        "/v3/device/list/fid/family-1/timestamp/1720000000"
    )


def test_login_application_error_is_response_error(monkeypatch: Any) -> None:
    client_module = _load_client_module()
    monkeypatch.setattr(client_module.time, "time", lambda: 1720000000.789)
    session = RecordingSession(
        [FakeResponse({"code": -101, "msg": "Timestamp requires 10 digits"})]
    )
    api = _api(client_module, session)

    try:
        asyncio.run(api.async_login("fake@example.invalid", "fake-password"))
    except client_module.LeproResponseError:
        pass
    else:
        raise AssertionError("expected LeproResponseError")


def test_product_config_http_failure_becomes_nonfatal_api_error() -> None:
    client_module = _load_client_module()
    session = RecordingSession([FakeResponse({"message": "unavailable"}, status=503)])
    api = _api(client_module, session)

    try:
        asyncio.run(api.async_product_configs())
    except client_module.LeproApiError:
        pass
    else:
        raise AssertionError("expected LeproApiError")

    assert session.requests[0]["url"].endswith("/pub/resources/config.series.json")


def test_mqtt_setup_failure_cleans_up_certificates_and_is_retryable(
    monkeypatch: Any, tmp_path: Path
) -> None:
    client_module = _load_client_module()
    created: list[Path] = []

    class TempDirectory:
        def __init__(self, prefix: str) -> None:
            self.name = str(tmp_path / prefix)
            Path(self.name).mkdir()
            created.append(Path(self.name))

        def cleanup(self) -> None:
            for path in Path(self.name).iterdir():
                path.unlink()
            Path(self.name).rmdir()

    class FailingMqttClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def tls_set(self, **_kwargs: Any) -> None:
            pass

        def reconnect_delay_set(self, **_kwargs: Any) -> None:
            pass

        def connect(self, *_args: Any) -> None:
            raise OSError("connection refused")

        def disconnect(self) -> None:
            pass

    monkeypatch.setattr(client_module.tempfile, "TemporaryDirectory", TempDirectory)
    monkeypatch.setattr(client_module.mqtt, "Client", FailingMqttClient)
    coordinator = client_module.LeproCoordinator.__new__(client_module.LeproCoordinator)
    coordinator.api = types.SimpleNamespace(uid="test")
    coordinator.tmp = None
    coordinator.client = None
    coordinator._on_connect = lambda *_args: None
    coordinator._on_disconnect = lambda *_args: None
    coordinator._on_message = lambda *_args: None

    try:
        coordinator._connect(
            {"host": "mqtt.example.invalid", "port": 8883},
            {
                "root": "-----BEGIN CERTIFICATE-----\nroot",
                "cert": "-----BEGIN CERTIFICATE-----\ncert",
                "key": "-----BEGIN PRIVATE KEY-----\nkey",
                "key_password": "secret",
            },
        )
    except client_module.LeproMqttError as err:
        assert str(err) == "Unable to connect to Lepro MQTT"
    else:
        raise AssertionError("expected LeproMqttError")

    assert coordinator.tmp is None
    assert coordinator.client is None
    assert created and not created[0].exists()


def test_mqtt_disconnect_notifies_entities_of_availability_change() -> None:
    client_module = _load_client_module()
    queued: list[tuple[Any, tuple[Any, ...]]] = []

    class Loop:
        def call_soon_threadsafe(self, callback: Any, *args: Any) -> None:
            queued.append((callback, args))

    notified: list[str] = []
    coordinator = client_module.LeproCoordinator.__new__(client_module.LeproCoordinator)
    coordinator.hass = types.SimpleNamespace(loop=Loop())
    coordinator.devices = {"light-1": {"did": "light-1"}}
    coordinator.listeners = {notified.append}
    coordinator.connected = True
    coordinator._stopping = False

    coordinator._on_disconnect(None, None, None, 1, None)

    assert coordinator.connected is False
    assert len(queued) == 1
    callback, args = queued.pop()
    callback(*args)
    assert notified == ["light-1"]


def test_certificate_http_failure_becomes_retryable_api_error() -> None:
    client_module = _load_client_module()
    api = _api(client_module, RecordingSession([FakeResponse("unavailable", status=503)]))

    try:
        asyncio.run(api.async_text("https://cert.example.invalid/client.pem"))
    except client_module.LeproApiError as err:
        assert str(err) == "Lepro certificate download failed"
    else:
        raise AssertionError("expected LeproApiError")
