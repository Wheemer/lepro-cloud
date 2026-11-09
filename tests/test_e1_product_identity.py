"""Product-ID recovery through real discovery, MQTT and native writers."""

from __future__ import annotations

import ast
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_platform_devices import FakeHass, _load_module

RED = "N01:P10001FF0000F210001001EU3V3000640000E1;"
GREEN = "N01:P1000100FF00F210001001EU3V3000640000E1;"


@pytest.mark.parametrize("product_id", [68, 115, "68", 115.0])
@pytest.mark.parametrize("series", ["__missing__", None, "", "E1", "D1", "E1-60"])
def test_product_id_recovers_full_discovery_and_native_path(product_id, series):
    client = _load_module("client")
    light = _load_module("light")
    switch = _load_module("switch")
    device_module = _load_module("device")
    api = client.LeproApi.__new__(client.LeproApi)
    raw = {"did": "123", "type": 1, "control": 3, "proId": product_id}
    if series != "__missing__":
        raw["series"] = series
    api._request = AsyncMock(
        side_effect=[
            {"list": [{"fid": "owner"}, {"fid": "shared"}]},
            {"list": [raw]},
            {"list": [{"did": "123", "series": "", "proId": None}]},
        ]
    )
    # Stale UI/family metadata must not override verified hardware identity.
    api.async_product_configs = AsyncMock(
        return_value=[
            {"series": "E1-30", "colorPicker": "rgb", "effect": "smartbulb"},
            {"series": "D1", "colorPicker": "", "effect": "null"},
        ]
    )

    async def run():
        co = client.LeproCoordinator.__new__(client.LeproCoordinator)
        co.api = api
        co.devices = {item["did"]: item for item in await api.async_devices()}
        co.states = {}
        co.effect_types = {}
        co._stopping = False
        co._notify = Mock()
        co._cancel_initial_state_retry = Mock()
        co.hass = SimpleNamespace(loop=asyncio.get_running_loop())
        co.command = Mock()
        await co._load_product_configs()
        lights, switches = [], []
        entry = SimpleNamespace(runtime_data=co)
        await light.async_setup_entry(None, entry, lambda values: lights.extend(values))
        await switch.async_setup_entry(
            None, entry, lambda values: switches.extend(values)
        )
        assert len(lights) == 1 and switches == []
        entity = lights[0]
        entity.hass = FakeHass()
        assert entity.supported_color_modes == {"hs", "color_temp"}
        assert entity._attr_device_info["model"] == "E1-30"
        assert entity._attr_unique_id == "lepro_cloud_123"
        assert device_module.product_series(co.devices["123"]) == "E1-30"
        assert co.devices["123"]["proId"] == product_id
        assert {"d50", "d52", "d53"} <= set(
            co._state_query_datapoints(co.devices["123"])
        )
        assert light.effect_family(co.devices["123"], co.effect_types) == "striplight"

        co._on_message(
            None,
            None,
            SimpleNamespace(
                topic="le/123/prp/getr",
                payload=json.dumps(
                    {"d": {"d1": 1, "d2": 2, "d50": RED, "d52": 500, "d53": 30}}
                ).encode(),
            ),
        )
        await asyncio.sleep(0)
        assert entity.hs_color == (0, 100)
        assert entity.brightness == 128
        await entity.async_turn_on(hs_color=(120, 100), brightness=255)
        assert co.command.call_args.args == (
            "123",
            {
                "d1": 1,
                "d2": 2,
                "d50": GREEN,
                "d52": 1000,
            },
        )
        await entity.async_turn_on(brightness=128)
        assert co.command.call_args.args == ("123", {"d1": 1, "d2": 2, "d52": 502})
        await entity.async_turn_on(color_temp_kelvin=2700, brightness=255)
        white = co.command.call_args.args[1]
        assert white["d2"] == 2 and white["d52"] == 1000
        assert "P4" in white["d50"]
        assert not {"d3", "d4", "d5"} & white.keys()
        # Commands do not fabricate broker readback.
        assert co.states["123"]["d50"] == RED

    asyncio.run(run())


def test_legacy_numeric_pid_alias_and_unknown_ids_are_bounded():
    device = _load_module("device")
    assert device.product_series({"pid": "68"}) == "E1-30"
    assert device.product_series({"proId": None, "pid": 115}) == "E1-30"
    # An explicit different product ID wins over a conflicting legacy alias.
    assert device.product_series({"proId": 77, "pid": 68, "series": "D1"}) == "D1"
    assert device.apk_product_series({"proId": True}) is None
    assert device.apk_product_series({"proId": 68.5}) is None
    assert device.apk_product_series({"proId": 999}) is None
    assert device.is_light({"proId": 68, "type": 2, "control": 3})
    assert not device.is_plug({"proId": 68, "type": 2, "control": 3})
    assert not device.is_supported_device({"proId": 68, "type": 3, "control": 3})


def test_no_product_id_does_not_guess_e1_from_user_name_or_led_count():
    device = _load_module("device")
    light = _load_module("light")
    from test_platform_devices import FakeCoordinator

    raw = {"type": 1, "series": "D1", "name": "E1-30", "d53": 30}
    assert device.product_series(raw) == "D1"
    assert light.LeproCloudLight(
        FakeCoordinator(), "fixture", raw
    ).supported_color_modes == {"brightness"}


def test_changed_product_identity_refreshes_profile_before_more_commands():
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co.api = SimpleNamespace(
        async_profile=AsyncMock(return_value={}),
        async_devices=AsyncMock(
            return_value=[
                {"did": "123", "type": 1, "control": 3, "series": "D1", "proId": 68}
            ]
        ),
    )
    co.devices = {
        "123": {"did": "123", "type": 1, "control": 3, "series": "D1", "proId": 77}
    }
    co._schedule_reload = Mock()
    asyncio.run(co._refresh_session())
    co._schedule_reload.assert_called_once()


def test_reclassified_e1_retires_old_switch_only_after_light_registration(monkeypatch):
    device = _load_module("device")
    source = (
        Path(__file__).resolve().parents[1]
        / "custom_components/lepro_cloud/__init__.py"
    ).read_text()
    node = next(
        item
        for item in ast.parse(source).body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_remove_obsolete_primary_entities"
    )
    entries = {
        "switch.old": SimpleNamespace(entity_id="switch.old", config_entry_id="entry"),
    }
    registered_light = []
    removed = []

    class Registry:
        def async_get_entity_id(self, domain, platform, unique_id):
            if domain == "light":
                return registered_light[0] if registered_light else None
            return "switch.old" if unique_id == "lepro_cloud_123_switch" else None

        def async_get(self, entity_id):
            return entries.get(entity_id)

        def async_remove(self, entity_id):
            removed.append(entity_id)
            entries.pop(entity_id)

    registry = Registry()
    fake_er = SimpleNamespace(async_get=lambda hass: registry)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", fake_er)
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"], "entity_registry", fake_er, raising=False
    )
    ns = {
        "__package__": "custom_components.lepro_cloud",
        "DOMAIN": "lepro_cloud",
        "HomeAssistant": object,
        "ConfigEntry": object,
        "LeproCoordinator": object,
    }
    # Execute only the checked-out cleanup function; do not import/start HA.
    exec(  # noqa: S102
        compile(ast.Module(body=[node], type_ignores=[]), "registry-cleanup", "exec"),
        ns,
    )
    cleanup = ns["_remove_obsolete_primary_entities"]
    co = SimpleNamespace(devices={"123": {"type": 2, "proId": 68, "control": 3}})
    assert device.is_light(co.devices["123"])
    entry = SimpleNamespace(entry_id="entry")
    cleanup(None, entry, co)
    assert removed == []
    entries["light.new"] = SimpleNamespace(
        entity_id="light.new", config_entry_id="entry"
    )
    registered_light.append("light.new")
    cleanup(None, entry, co)
    assert removed == ["switch.old"]
    assert "light.new" in entries


@pytest.mark.parametrize("product_id", [68, 115])
@pytest.mark.parametrize("types", [(2,), (1, 2), (2, 1)])
def test_conflicting_type_through_discovery_and_platform_setup(product_id, types):
    client = _load_module("client")
    light = _load_module("light")
    switch = _load_module("switch")
    device = _load_module("device")
    api = client.LeproApi.__new__(client.LeproApi)
    api._request = AsyncMock(
        side_effect=[
            {"list": [{"fid": str(i)} for i in range(len(types))]},
            *[
                {
                    "list": [
                        {
                            "did": "123",
                            "type": value,
                            "control": 3,
                            "proId": product_id,
                            "series": "D1",
                        }
                    ]
                }
                for value in types
            ],
        ]
    )
    api.async_product_configs = AsyncMock(return_value=[])

    async def run():
        co = client.LeproCoordinator.__new__(client.LeproCoordinator)
        co.api = api
        co.devices = {
            item["did"]: item
            for item in await api.async_devices()
            if device.is_supported_device(item)
        }
        co.states = {"123": {"d1": 1, "d2": 2, "d52": 500, "d53": 30}}
        co.effect_types = {}
        co.command = Mock()
        await co._load_product_configs()
        lights, switches = [], []
        entry = SimpleNamespace(runtime_data=co)
        await light.async_setup_entry(None, entry, lambda es: lights.extend(es))
        await switch.async_setup_entry(None, entry, lambda es: switches.extend(es))
        assert len(lights) == 1 and switches == []
        assert co.devices["123"]["type"] == types[-1]
        assert device.device_type(co.devices["123"]) == 1
        entity = lights[0]
        assert entity.supported_color_modes == {"hs", "color_temp"}
        assert entity._attr_unique_id == "lepro_cloud_123"
        assert {"d50", "d52", "d53"} <= set(
            co._state_query_datapoints(co.devices["123"])
        )
        entity.hass = FakeHass()
        await entity.async_turn_on(hs_color=(120, 100), brightness=255)
        assert co.command.call_args.args == (
            "123",
            {"d1": 1, "d2": 2, "d50": GREEN, "d52": 1000},
        )

    asyncio.run(run())


@pytest.mark.parametrize("field", ["type", "deviceType", "devType"])
def test_verified_product_classification_handles_type_aliases(field):
    device = _load_module("device")
    raw = {field: "2", "proId": 115, "control": 3}
    assert device.is_light(raw)
    assert not device.is_plug(raw)


@pytest.mark.parametrize(
    "metadata",
    [
        {"proId": 77, "series": "E1-30"},
        {"proId": 999, "series": "E1-30"},
        {"series": "E1-30"},
        {"name": "E1-30"},
    ],
)
def test_unverified_e1_label_does_not_turn_real_plug_into_light(metadata):
    device = _load_module("device")
    raw = {"type": 2, "control": 3, **metadata}
    assert device.is_plug(raw)
    assert not device.is_light(raw)
