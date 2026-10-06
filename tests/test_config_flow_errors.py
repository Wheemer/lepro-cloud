"""Tests for Lepro config-flow error mapping."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import logging
from pathlib import Path
import sys
import types
from typing import Any


def _load_config_flow_module() -> Any:
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    homeassistant_const = types.ModuleType("homeassistant.const")
    homeassistant_const.CONF_PASSWORD = "password"
    homeassistant_const.CONF_USERNAME = "username"
    homeassistant_const.Platform = types.SimpleNamespace(LIGHT="light", SWITCH="switch")

    class ConfigFlow:
        def __init_subclass__(cls, **_kwargs: Any) -> None:
            super().__init_subclass__()

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigFlow = ConfigFlow
    homeassistant_core = types.ModuleType("homeassistant.core")
    homeassistant_core.HomeAssistant = object
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None

    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Required = lambda key, default=None: key
    voluptuous.In = lambda values: values
    voluptuous.Schema = lambda schema: schema

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

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.const"] = homeassistant_const
    sys.modules["homeassistant.core"] = homeassistant_core
    sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client
    sys.modules["voluptuous"] = voluptuous
    sys.modules.setdefault("paho", paho)
    sys.modules["paho.mqtt"] = paho_mqtt
    sys.modules["paho.mqtt.client"] = paho_mqtt_client

    package = types.ModuleType("custom_components.lepro_cloud")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "lepro_cloud")]
    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    sys.modules["custom_components.lepro_cloud"] = package

    config_flow_path = Path(package.__path__[0]) / "config_flow.py"
    spec = spec_from_file_location(
        "custom_components.lepro_cloud.config_flow", config_flow_path
    )
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_flow_error_distinguishes_response_failures() -> None:
    module = _load_config_flow_module()

    assert module._flow_error(module.LeproAuthError("bad credentials")) == "invalid_auth"
    assert (
        module._flow_error(module.LeproResponseError("Timestamp requires 10 digits"))
        == "invalid_response"
    )
    assert module._flow_error(module.LeproApiError("network down")) == "cannot_connect"


def test_log_api_error_includes_type_and_safe_message(caplog: Any) -> None:
    module = _load_config_flow_module()

    caplog.set_level(logging.WARNING, logger="custom_components.lepro_cloud.config_flow")
    module._log_api_error(module.LeproResponseError("Timestamp requires 10 digits"))

    assert "LeproResponseError" in caplog.text
    assert "Timestamp requires 10 digits" in caplog.text
    assert "username" not in caplog.text
    assert "password" not in caplog.text
    assert "token" not in caplog.text
    assert "secret" not in caplog.text


def test_login_input_matches_app_whitespace_trimming() -> None:
    """The Android login activity trims both credentials before submission."""
    assert "password = user_input[CONF_PASSWORD].strip()" in (
        Path(__file__).resolve().parents[1]
        .joinpath("custom_components", "lepro_cloud", "config_flow.py")
        .read_text(encoding="utf-8")
    )
