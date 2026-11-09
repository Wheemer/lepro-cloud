"""Discovery through platform creation, without starting Home Assistant."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_platform_devices import _load_module


@pytest.mark.parametrize("remote_picker", ["diyEaves", None, ""])
@pytest.mark.parametrize("device_type", [1, "1"])
@pytest.mark.parametrize(
    "state",
    [
        {},
        {"online": 1, "d1": 0},
        {"online": 1, "d1": 1},
        {"d1": 1, "d2": 2, "d50": "app-pattern", "d52": 500, "d53": 30},
    ],
)
def test_e1_discovery_to_entity_cannot_silently_become_onoff(
    remote_picker, device_type, state, caplog
):
    client = _load_module("client")
    light = _load_module("light")
    switch = _load_module("switch")
    device = _load_module("device")
    api = client.LeproApi.__new__(client.LeproApi)
    api._request = AsyncMock(
        side_effect=[
            {"list": [{"fid": "owner"}, {"fid": "shared"}]},
            {
                "list": [
                    {
                        "did": "fixture-e1",
                        "type": device_type,
                        "control": 2,
                        "series": "E1-30",
                        "name": "Fixture",
                    }
                ]
            },
            {"list": [{"did": "fixture-e1", "type": None, "series": ""}]},
        ]
    )
    api.async_product_configs = AsyncMock(
        return_value=[{"series": "E1-30", "colorPicker": remote_picker, "effect": None}]
    )
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co.api = api
    co.effect_types = {}
    co.states = {"fixture-e1": dict(state)}

    async def discover():
        found = await api.async_devices()
        co.devices = {
            item["did"]: item for item in found if device.is_supported_device(item)
        }
        await co._load_product_configs()
        entry = SimpleNamespace(runtime_data=co)
        lights, switches = [], []
        await light.async_setup_entry(None, entry, lambda values: lights.extend(values))
        await switch.async_setup_entry(
            None, entry, lambda values: switches.extend(values)
        )
        return lights, switches

    with caplog.at_level("DEBUG", logger="custom_components.lepro_cloud.light"):
        lights, switches = asyncio.run(discover())
    assert len(lights) == 1
    assert switches == []
    entity = lights[0]
    assert entity.device["type"] == device_type
    assert entity.device["series"] == "E1-30"
    assert entity._attr_unique_id == "lepro_cloud_fixture-e1"
    modes = entity.supported_color_modes
    assert modes == {"hs", "color_temp"}
    # HA frontend lightSupportsBrightness includes every one of these modes.
    assert modes & {"brightness", "hs", "color_temp"}
    assert "onoff" not in modes
    assert "Lepro light setup: series=E1-30 type=1 control=2" in caplog.text
    assert "supported_color_modes=" in caplog.text
    assert "fixture-e1" not in caplog.text
    assert "Fixture" not in caplog.text


def test_explicit_plug_classification_is_a_switch_not_a_hidden_color_light():
    _load_module("client")
    light = _load_module("light")
    switch = _load_module("switch")
    co = SimpleNamespace(
        devices={
            "fixture-e1": {
                "did": "fixture-e1",
                "type": 2,
                "control": 2,
                "series": "E1-30",
            }
        }
    )
    entry = SimpleNamespace(runtime_data=co)
    lights, switches = [], []

    async def setup():
        await light.async_setup_entry(None, entry, lambda values: lights.extend(values))
        await switch.async_setup_entry(
            None, entry, lambda values: switches.extend(values)
        )

    asyncio.run(setup())
    assert not lights
    assert len(switches) == 1
    assert isinstance(switches[0], switch.LeproCloudPlugSwitch)


def test_blank_picker_is_still_valid_for_the_apk_dimmer_only_profile():
    light = _load_module("light")
    from test_platform_devices import FakeCoordinator

    entity = light.LeproCloudLight(
        FakeCoordinator(), "fixture", {"type": 1, "series": "D1", "_color_picker": ""}
    )
    assert entity.supported_color_modes == {"brightness"}


def test_legacy_cached_blank_picker_cannot_erase_known_e1_colour():
    light = _load_module("light")
    from test_platform_devices import FakeCoordinator

    entity = light.LeproCloudLight(
        FakeCoordinator(),
        "fixture",
        {"type": 1, "series": "E1-30", "_color_picker": ""},
    )
    assert entity.supported_color_modes == {"hs", "color_temp"}
