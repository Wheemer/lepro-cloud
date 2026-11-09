"""Product-ID recovery through real discovery, MQTT and native writers."""

from __future__ import annotations

import asyncio
import json
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
    assert not device.is_light({"proId": 68, "type": 2, "control": 3})
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
