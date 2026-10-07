"""Tests for Home Assistant platform device classification and plug switches."""

from __future__ import annotations

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types
from typing import Any, Callable


PACKAGE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "lepro_cloud"


def _install_platform_import_stubs() -> None:
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []

    light_component = types.ModuleType("homeassistant.components.light")
    light_component.ATTR_BRIGHTNESS = "brightness"
    light_component.ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
    light_component.ATTR_EFFECT = "effect"
    light_component.ATTR_HS_COLOR = "hs_color"
    light_component.ColorMode = types.SimpleNamespace(
        BRIGHTNESS="brightness", COLOR_TEMP="color_temp", HS="hs"
    )
    light_component.LightEntity = RecordingEntity
    light_component.LightEntityFeature = type("LightEntityFeature", (int,), {"EFFECT": 1})

    switch_component = types.ModuleType("homeassistant.components.switch")
    switch_component.SwitchEntity = RecordingEntity

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object

    homeassistant_core = types.ModuleType("homeassistant.core")
    homeassistant_core.HomeAssistant = object

    entity = types.ModuleType("homeassistant.helpers.entity")
    entity.EntityCategory = types.SimpleNamespace(CONFIG="config")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = Callable[..., None]

    homeassistant_const = types.ModuleType("homeassistant.const")
    homeassistant_const.Platform = types.SimpleNamespace(LIGHT="light", SWITCH="switch")

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
    sys.modules.setdefault(
        "homeassistant.components", types.ModuleType("homeassistant.components")
    )
    sys.modules["homeassistant.components.light"] = light_component
    sys.modules["homeassistant.components.switch"] = switch_component
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = homeassistant_core
    sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
    sys.modules["homeassistant.helpers.entity"] = entity
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
    sys.modules["homeassistant.const"] = homeassistant_const
    sys.modules.setdefault("paho", paho)
    sys.modules["paho.mqtt"] = paho_mqtt
    sys.modules["paho.mqtt.client"] = paho_mqtt_client

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client


def _load_module(name: str) -> Any:
    _install_platform_import_stubs()
    package = types.ModuleType("custom_components.lepro_cloud")
    package.__path__ = [str(PACKAGE_PATH)]
    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    sys.modules["custom_components.lepro_cloud"] = package

    spec = spec_from_file_location(
        f"custom_components.lepro_cloud.{name}", PACKAGE_PATH / f"{name}.py"
    )
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RecordingEntity:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.write_count = 0
        self.remove_callbacks: list[Callable[[], None]] = []

    def async_write_ha_state(self) -> None:
        self.write_count = getattr(self, "write_count", 0) + 1

    def async_on_remove(self, callback: Callable[[], None]) -> None:
        if not hasattr(self, "remove_callbacks"):
            self.remove_callbacks = []
        self.remove_callbacks.append(callback)


class FakeHass:
    async def async_add_executor_job(self, target: Callable[..., Any], *args: Any) -> Any:
        return target(*args)


class FakeCoordinator:
    def __init__(self) -> None:
        self.devices = {
            "light-1": {"did": "light-1", "type": 1, "name": "Light"},
            "plug-1": {"did": "plug-1", "type": 2, "name": "Plug"},
            "legacy-1": {"did": "legacy-1", "name": "Unknown"},
        }
        self.states: dict[str, dict[str, Any]] = {}
        self.effect_types: dict[str, str] = {}
        self.connected = True
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.listeners: list[Callable[[str], None]] = []

    def command(self, did: str, values: dict[str, Any]) -> None:
        self.commands.append((did, values))

    def listen(self, listener: Callable[[str], None]) -> Callable[[], None]:
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)


def test_platforms_expose_only_verified_device_types() -> None:
    device = _load_module("device")
    light = _load_module("light")
    switch = _load_module("switch")

    assert device.device_type({"type": 1}) == device.DEVICE_TYPE_LIGHT
    assert device.device_type({"deviceType": "2"}) == device.DEVICE_TYPE_PLUG
    assert device.device_type({"type": "camera"}) is None
    assert device.device_type({}) is None
    assert device.is_light({"type": 1})
    assert device.is_plug({"type": 2})

    assert light._is_supported_light({"type": 1})
    assert light._is_supported_light({"deviceType": "1"})
    assert not light._is_supported_light({"type": 2})
    assert not light._is_supported_light({})

    assert switch._is_supported_switch({"type": 2})
    assert switch._is_supported_switch({"devType": "2"})
    assert not switch._is_supported_switch({"type": 1})
    assert not switch._is_supported_switch({})


def test_setup_entry_adds_lights_and_switches() -> None:
    light = _load_module("light")
    switch = _load_module("switch")
    coordinator = FakeCoordinator()
    entry = types.SimpleNamespace(runtime_data=coordinator)

    added_lights: list[Any] = []
    added_switches: list[Any] = []

    asyncio.run(
        light.async_setup_entry(
            FakeHass(), entry, lambda entities: added_lights.extend(entities)
        )
    )
    asyncio.run(
        switch.async_setup_entry(
            FakeHass(), entry, lambda entities: added_switches.extend(entities)
        )
    )

    assert [entity.device_id for entity in added_lights] == ["light-1"]
    assert [entity.device_id for entity in added_switches] == ["plug-1"]


def test_plug_switch_uses_d1_state_command_and_availability() -> None:
    switch = _load_module("switch")
    coordinator = FakeCoordinator()
    entity = switch.LeproCloudPlugSwitch(
        coordinator, "plug-1", coordinator.devices["plug-1"]
    )
    entity.hass = FakeHass()

    assert entity.available is True
    assert entity.is_on is None

    asyncio.run(entity.async_turn_on())

    assert coordinator.commands == [("plug-1", {"d1": 1})]
    assert coordinator.states["plug-1"]["d1"] == 1
    assert entity.is_on is True
    assert entity.write_count == 1

    coordinator.states["plug-1"]["online"] = 0
    assert entity.available is False

    asyncio.run(entity.async_turn_off())

    assert coordinator.commands[-1] == ("plug-1", {"d1": 0})
    assert entity.is_on is False


def test_p1_plug_exposes_and_controls_its_button_lock() -> None:
    switch = _load_module("switch")
    coordinator = FakeCoordinator()
    device = {"did": "p1-1", "type": 2, "series": "P1", "name": "P1 Plug"}
    coordinator.devices["p1-1"] = device
    entry = types.SimpleNamespace(runtime_data=coordinator)
    entities: list[Any] = []

    asyncio.run(
        switch.async_setup_entry(FakeHass(), entry, lambda added: entities.extend(added))
    )

    lock = next(entity for entity in entities if entity.device_id == "p1-1" and entity._attr_name == "Button Lock")
    lock.hass = FakeHass()
    assert lock._attr_entity_category == "config"
    assert lock.is_on is None

    asyncio.run(lock.async_turn_on())
    assert coordinator.commands[-1] == ("p1-1", {"d102": 1})
    assert lock.is_on is True

    asyncio.run(lock.async_turn_off())
    assert coordinator.commands[-1] == ("p1-1", {"d102": 0})
    assert lock.is_on is False

    memory = next(
        entity
        for entity in entities
        if entity.device_id == "p1-1" and entity._attr_name == "Power Memory"
    )
    memory.hass = FakeHass()
    assert memory._attr_entity_category == "config"
    assert memory.is_on is None

    asyncio.run(memory.async_turn_on())
    assert coordinator.commands[-1] == ("p1-1", {"d100": 1})
    assert memory.is_on is True

    asyncio.run(memory.async_turn_off())
    assert coordinator.commands[-1] == ("p1-1", {"d100": 0})
    assert memory.is_on is False

    indicator = next(
        entity
        for entity in entities
        if entity.device_id == "p1-1" and entity._attr_name == "Indicator Light"
    )
    indicator.hass = FakeHass()
    assert indicator.is_on is None
    asyncio.run(indicator.async_turn_on())
    assert coordinator.commands[-1] == ("p1-1", {"d101": "100000000"})
    assert indicator.is_on is True
    asyncio.run(indicator.async_turn_off())
    assert coordinator.commands[-1] == ("p1-1", {"d101": "000000000"})
    assert indicator.is_on is False


def test_stv1_exposes_verified_status_and_auto_toggle_switches() -> None:
    switch = _load_module("switch")
    coordinator = FakeCoordinator()
    device = {"did": "stv-1", "type": 1, "series": "STV1", "name": "TV Strip"}
    coordinator.devices["stv-1"] = device
    coordinator.states["stv-1"] = {"online": 1, "d157": 1, "d172": 0}
    entry = types.SimpleNamespace(runtime_data=coordinator)
    entities: list[Any] = []
    asyncio.run(switch.async_setup_entry(FakeHass(), entry, lambda added: entities.extend(added)))
    settings = [entity for entity in entities if entity.device_id == "stv-1"]
    assert [entity._attr_name for entity in settings] == ["Status LED", "Auto-Toggle Lights"]
    assert all(entity._attr_entity_category == "config" for entity in settings)
    assert settings[0].is_on is True
    assert settings[1].is_on is False
    settings[1].hass = FakeHass()
    asyncio.run(settings[1].async_turn_on())
    assert coordinator.commands[-1] == ("stv-1", {"d172": 1})


def test_light_reports_modes_from_state_datapoints() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    entity = light.LeproCloudLight(
        coordinator, "light-1", coordinator.devices["light-1"]
    )

    assert entity.supported_color_modes == {"brightness"}
    assert entity.color_mode == "brightness"
    assert entity.brightness is None

    coordinator.states["light-1"] = {
        "d2": 0,
        "d3": 500,
        "d4": 0,
        "d5": "00b403e803e8",
    }

    assert entity.supported_color_modes == {"color_temp", "hs"}
    assert entity.color_mode == "color_temp"
    assert entity.brightness == 128
    assert entity.color_temp_kelvin == 2700
    assert entity.hs_color == (180.0, 100.0)

    coordinator.states["light-1"]["d2"] = 1
    assert entity.color_mode == "hs"
    assert entity.brightness == 255


def test_light_turn_on_honors_brightness_color_temp_and_hs_color() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    coordinator.states["light-1"] = {"d3": 64, "d4": 500, "d5": "000000000000"}
    entity = light.LeproCloudLight(
        coordinator, "light-1", coordinator.devices["light-1"]
    )
    entity.hass = FakeHass()

    asyncio.run(entity.async_turn_on(brightness=128))
    assert coordinator.commands[-1] == ("light-1", {"d1": 1, "d2": 0, "d3": 502, "d4": 500})

    asyncio.run(entity.async_turn_on(color_temp_kelvin=2700))
    assert coordinator.commands[-1] == (
        "light-1",
        {"d1": 1, "d2": 0, "d3": 502, "d4": 0},
    )

    asyncio.run(entity.async_turn_on(hs_color=(120, 50), brightness=255))
    assert coordinator.commands[-1] == (
        "light-1",
        {"d1": 1, "d2": 1, "d5": "007801F403E8"},
    )


def test_scene_mode_uses_a_supported_color_mode() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    coordinator.states["light-1"] = {
        "d2": 2,
        "d4": 500,
        "d5": "007801F403E8",
    }
    entity = light.LeproCloudLight(
        coordinator, "light-1", coordinator.devices["light-1"]
    )

    assert entity.supported_color_modes == {"hs", "color_temp"}
    assert entity.color_mode == "hs"


def test_tb1_uses_app_supplied_multipart_scenes() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    device = coordinator.devices["light-1"]
    device.update(
        {
            "series": "TB1",
            "scenes": [
                {
                    "scene": "Aurora",
                    "earthlight": {
                        "dp": "d50",
                        "res": "N01:P10001FF9700F2100010054R6U200020054V2000640000E1;",
                    },
                }
            ],
        }
    )
    coordinator.effect_types = {"TB1": "earthlight"}
    coordinator.states["light-1"] = {"d52": 500}
    entity = light.LeproCloudLight(coordinator, "light-1", device)
    entity.hass = FakeHass()

    assert entity.effect_list == ["Aurora"]
    assert entity.supported_features == 1
    asyncio.run(entity.async_turn_on(effect="Aurora"))
    assert coordinator.commands[-1] == (
        "light-1",
        {
            "d1": 1,
            "d2": 2,
            "d50": "N01:P10001FF9700F2100010054R6U200020054V2000640000E1;",
            "d52": 502,
        },
    )
    assert entity.effect == "Aurora"


def test_striplight_uses_neonlight_scene_fallback() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    device = coordinator.devices["light-1"]
    device.update(
        {
            "series": "S1-5",
            "scenes": [
                {
                    "name": "Wave",
                    "neonlight": {"dp": "d50", "res": "N01:P10001FF9700E1;"},
                }
            ],
        }
    )
    coordinator.effect_types = {"S1-5": "striplight"}
    entity = light.LeproCloudLight(coordinator, "light-1", device)
    entity.hass = FakeHass()

    assert entity.effect_list == ["Wave"]
    asyncio.run(entity.async_turn_on(effect="Wave"))
    assert coordinator.commands[-1] == (
        "light-1",
        {"d1": 1, "d2": 2, "d50": "N01:P10001FF9700E1;", "d52": 1000},
    )


def test_known_rgbic_uses_d52_before_its_first_state_report() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    device = coordinator.devices["light-1"]
    device["series"] = "S1-10"
    entity = light.LeproCloudLight(coordinator, "light-1", device)

    assert entity._brightness_datapoint == "d52"


def test_rgbic_light_uses_its_own_brightness_datapoint() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    coordinator.states["light-1"] = {"d2": 2, "d52": 500}
    entity = light.LeproCloudLight(
        coordinator, "light-1", coordinator.devices["light-1"]
    )
    entity.hass = FakeHass()

    assert entity.brightness == 128
    asyncio.run(entity.async_turn_on(brightness=128))
    assert coordinator.commands[-1] == ("light-1", {"d1": 1, "d2": 2, "d52": 502})


def test_light_preserves_non_d50_scene_payloads() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    device = coordinator.devices["light-1"]
    device.update(
        {
            "series": "B1",
            "scenes": [
                {
                    "name": "Breath",
                    "smartbulb": {"dp": "d6", "res": "0001"},
                }
            ],
        }
    )
    coordinator.effect_types = {"B1": "smartbulb"}
    entity = light.LeproCloudLight(coordinator, "light-1", device)
    entity.hass = FakeHass()

    assert entity.effect_list == ["Breath"]
    asyncio.run(entity.async_turn_on(effect="Breath"))
    assert coordinator.commands[-1] == ("light-1", {"d1": 1, "d2": 2, "d6": "0001"})


def test_light_uses_root_d5_scene_payload_without_product_mapping() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    device = coordinator.devices["light-1"]
    device.update(
        {
            "series": "B1",
            "scenes": [
                {
                    "name": "Gradient",
                    "d5": {"dp": "d5", "res": "007801F403E8"},
                }
            ],
        }
    )
    entity = light.LeproCloudLight(coordinator, "light-1", device)
    entity.hass = FakeHass()

    assert entity.effect_list == ["Gradient"]
    asyncio.run(entity.async_turn_on(effect="Gradient", brightness=128))
    assert coordinator.commands[-1] == (
        "light-1",
        {"d1": 1, "d2": 2, "d5": "007801F401F6"},
    )


def test_light_updates_brightness_for_hsv_scene_payloads() -> None:
    light = _load_module("light")
    coordinator = FakeCoordinator()
    device = coordinator.devices["light-1"]
    device.update(
        {
            "series": "B1",
            "scenes": [
                {
                    "name": "Gradient",
                    "smartbulb": {"dp": "d5", "res": "007801F403E8"},
                }
            ],
        }
    )
    coordinator.effect_types = {"B1": "smartbulb"}
    entity = light.LeproCloudLight(coordinator, "light-1", device)
    entity.hass = FakeHass()

    asyncio.run(entity.async_turn_on(effect="Gradient", brightness=128))
    assert coordinator.commands[-1] == (
        "light-1",
        {"d1": 1, "d2": 2, "d5": "007801F401F6"},
    )
    assert entity.effect == "Gradient"
