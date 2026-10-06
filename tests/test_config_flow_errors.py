"""Tests for Lepro config-flow error mapping."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import asyncio
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

        def __init__(self) -> None:
            self.context: dict[str, Any] = {}
            self.flow_id = "flow-id"
            self.handler = "lepro_cloud"
            self.hass: Any = None

        async def async_set_unique_id(
            self, unique_id: str | None = None, *, raise_on_progress: bool = True
        ) -> Any:
            self.context["unique_id"] = unique_id
            return self.hass.config_entries.async_entry_for_domain_unique_id(
                self.handler, unique_id
            )

        def _abort_if_unique_id_configured(self) -> None:
            return None

        def _get_reconfigure_entry(self) -> Any:
            return self.hass.config_entries.reconfigure_entry

        def async_show_form(self, **kwargs: Any) -> dict[str, Any]:
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs: Any) -> dict[str, Any]:
            return {"type": "create_entry", **kwargs}

        def async_update_reload_and_abort(self, entry: Any, **kwargs: Any) -> dict[str, Any]:
            data_updates = kwargs.get("data_updates", {})
            self.hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, **data_updates},
                title=kwargs.get("title", entry.title),
                unique_id=kwargs.get("unique_id", entry.unique_id),
            )
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return {"type": "abort", "reason": "reconfigure_successful"}

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigFlow = ConfigFlow
    homeassistant_core = types.ModuleType("homeassistant.core")
    homeassistant_core.HomeAssistant = object
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    selector = types.ModuleType("homeassistant.helpers.selector")
    selector.SelectOptionDict = lambda **kwargs: kwargs
    selector.SelectSelectorConfig = lambda **kwargs: kwargs
    selector.SelectSelector = lambda config: {"selector": "select", **config}

    voluptuous = types.ModuleType("voluptuous")
    class RequiredMarker:
        def __init__(self, key: str, default: Any = None) -> None:
            self.key = key
            self.default = default

        def __hash__(self) -> int:
            return hash((self.key, self.default))

        def __eq__(self, other: Any) -> bool:
            return (
                isinstance(other, RequiredMarker)
                and other.key == self.key
                and other.default == self.default
            )

    voluptuous.Required = RequiredMarker
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
    sys.modules["homeassistant.helpers.selector"] = selector
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


def _entry(
    *,
    entry_id: str,
    username: str,
    password: str,
    region: str,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        entry_id=entry_id,
        data={"username": username, "password": password, "region": region},
        title=f"Lepro Cloud ({username})",
        unique_id=f"{region}:{username.lower()}",
    )


class _ConfigEntries:
    def __init__(self, entries: list[Any], reconfigure_entry: Any) -> None:
        self.entries = entries
        self.reconfigure_entry = reconfigure_entry
        self.reloads: list[str] = []

    def async_entry_for_domain_unique_id(
        self, _domain: str, unique_id: str | None
    ) -> Any:
        return next(
            (entry for entry in self.entries if entry.unique_id == unique_id),
            None,
        )

    def async_update_entry(self, entry: Any, **kwargs: Any) -> bool:
        if "data" in kwargs:
            entry.data = kwargs["data"]
        if "title" in kwargs:
            entry.title = kwargs["title"]
        if "unique_id" in kwargs:
            entry.unique_id = kwargs["unique_id"]
        return True

    def async_schedule_reload(self, entry_id: str) -> None:
        self.reloads.append(entry_id)


def test_region_choices_use_human_labels_with_stored_values() -> None:
    module = _load_config_flow_module()

    assert module.REGION_CHOICES == {
        "north_america": "North America",
        "europe": "Europe",
        "far_east": "Far East",
    }
    region_field = next(
        field for field in module._credentials_schema() if field.key == "region"
    )
    assert module._credentials_schema()[region_field] == module.REGION_CHOICES
    assert "api-" not in str(module._credentials_schema())


def test_reconfigure_form_prefills_username_and_region_not_password() -> None:
    module = _load_config_flow_module()
    entry = _entry(
        entry_id="one",
        username="user@example.com",
        password="secret",
        region="europe",
    )
    flow = module.LeproCloudFlow()
    flow.hass = types.SimpleNamespace(
        config_entries=_ConfigEntries([entry], reconfigure_entry=entry)
    )

    result = asyncio.run(flow.async_step_reconfigure())

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"
    fields = {field.key: field.default for field in result["data_schema"]}
    assert fields["username"] == "user@example.com"
    assert fields["region"] == "europe"
    assert fields["password"] is None


def test_reconfigure_updates_and_reloads_existing_entry(monkeypatch: Any) -> None:
    module = _load_config_flow_module()
    entry = _entry(
        entry_id="one",
        username="old@example.com",
        password="old-password",
        region="north_america",
    )
    config_entries = _ConfigEntries([entry], reconfigure_entry=entry)
    flow = module.LeproCloudFlow()
    flow.hass = types.SimpleNamespace(config_entries=config_entries)

    class Api:
        def __init__(self, hass: Any, region: str) -> None:
            assert hass is flow.hass
            assert region == "europe"

        async def async_login(self, username: str, password: str) -> None:
            assert username == "new@example.com"
            assert password == "new-password"

    monkeypatch.setattr(module, "LeproApi", Api)

    result = asyncio.run(
        flow.async_step_reconfigure(
            {
                "username": " new@example.com ",
                "password": " new-password ",
                "region": "europe",
            }
        )
    )

    assert result == {"type": "abort", "reason": "reconfigure_successful"}
    assert entry.entry_id == "one"
    assert entry.title == "Lepro Cloud (new@example.com)"
    assert entry.unique_id == "europe:new@example.com"
    assert entry.data == {
        "username": "new@example.com",
        "password": "new-password",
        "region": "europe",
    }
    assert config_entries.reloads == ["one"]


def test_reconfigure_preserves_unique_id_when_account_region_unchanged(
    monkeypatch: Any,
) -> None:
    module = _load_config_flow_module()
    entry = _entry(
        entry_id="one",
        username="User@Example.com",
        password="old-password",
        region="north_america",
    )
    config_entries = _ConfigEntries([entry], reconfigure_entry=entry)
    flow = module.LeproCloudFlow()
    flow.hass = types.SimpleNamespace(config_entries=config_entries)

    class Api:
        def __init__(self, hass: Any, region: str) -> None:
            pass

        async def async_login(self, username: str, password: str) -> None:
            pass

    monkeypatch.setattr(module, "LeproApi", Api)

    asyncio.run(
        flow.async_step_reconfigure(
            {
                "username": " User@Example.com ",
                "password": " updated ",
                "region": "north_america",
            }
        )
    )

    assert entry.unique_id == "north_america:user@example.com"


def test_reconfigure_rejects_duplicate_other_entry(monkeypatch: Any) -> None:
    module = _load_config_flow_module()
    entry = _entry(
        entry_id="one",
        username="one@example.com",
        password="one-password",
        region="north_america",
    )
    duplicate = _entry(
        entry_id="two",
        username="two@example.com",
        password="two-password",
        region="europe",
    )
    flow = module.LeproCloudFlow()
    flow.hass = types.SimpleNamespace(
        config_entries=_ConfigEntries([entry, duplicate], reconfigure_entry=entry)
    )

    class Api:
        def __init__(self, hass: Any, region: str) -> None:
            raise AssertionError("duplicate should be rejected before login")

    monkeypatch.setattr(module, "LeproApi", Api)

    result = asyncio.run(
        flow.async_step_reconfigure(
            {
                "username": " TWO@example.com ",
                "password": " new-password ",
                "region": "europe",
            }
        )
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}
    assert entry.data["username"] == "one@example.com"
