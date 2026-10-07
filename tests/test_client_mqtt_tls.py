"""Tests for Lepro MQTT TLS setup."""

from __future__ import annotations

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
    paho_mqtt_client.Client = RecordingMqttClient
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


class RecordingMqttClient:
    last_instance: "RecordingMqttClient | None" = None

    def __init__(self, *_args: Any, **kwargs: Any) -> None:
        self.tls_kwargs: dict[str, Any] | None = None
        self.client_id = kwargs.get("client_id")
        self.connected_to: tuple[str, int, int] | None = None
        RecordingMqttClient.last_instance = self

    def tls_set(self, **kwargs: Any) -> None:
        self.tls_kwargs = kwargs

    def reconnect_delay_set(self, **_kwargs: Any) -> None:
        pass

    def connect(self, host: str, port: int, keepalive: int) -> None:
        self.connected_to = (host, port, keepalive)

    def loop_start(self) -> None:
        pass


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


def test_connect_passes_login_secret_as_tls_key_password() -> None:
    client_module = _load_client_module()
    coordinator = client_module.LeproCoordinator.__new__(client_module.LeproCoordinator)
    coordinator.api = types.SimpleNamespace(uid="user-id")
    coordinator.devices = {}
    coordinator.client = None
    coordinator.connected = False
    coordinator._stopping = False

    coordinator._connect(
        {"host": "mqtt.example.invalid", "port": 8883},
        {
            "root": "root-ca",
            "cert": "client-cert",
            "key": "private-key-placeholder",
            "key_password": "login-secret",
        },
    )

    mqtt_client = RecordingMqttClient.last_instance
    assert mqtt_client is not None
    assert mqtt_client.client_id.startswith("lepro-app-")
    assert len(mqtt_client.client_id) == len("lepro-app-") + 32
    assert mqtt_client.tls_kwargs is not None
    assert mqtt_client.tls_kwargs["keyfile_password"] == "login-secret"
    assert Path(mqtt_client.tls_kwargs["keyfile"]).read_text(encoding="utf-8") == (
        "private-key-placeholder"
    )
    coordinator.tmp.cleanup()
