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


@pytest.mark.parametrize("report_before_entity", [False, True])
def test_e1_initial_mqtt_report_is_not_lost_across_entity_creation(
    report_before_entity,
):
    client = _load_module("client")
    light = _load_module("light")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co.devices = {
        "fixture": {
            "did": "fixture",
            "type": 1,
            "series": "E1-30",
            "control": 2,
            "_color_picker": "diyEaves",
        }
    }
    co.states = {}
    co.effect_types = {"E1-30": "striplight"}
    co.listeners = set()
    co._fresh = set()
    co._stopping = False
    co.connected = True
    report = {
        "online": 1,
        "d1": 1,
        "d2": 2,
        "d52": 500,
        "d53": 30,
        "d50": "N01:P10001FF0000F210001001EU3V3000640000E1;",
    }
    if report_before_entity:
        co._apply_report("fixture", report)
    entity = light.LeproCloudLight(co, "fixture", co.devices["fixture"])
    asyncio.run(entity.async_added_to_hass())
    if not report_before_entity:
        co._apply_report("fixture", report)
        assert entity.write_count == 1
    assert entity.supported_color_modes == {"hs", "color_temp"}
    assert entity.brightness == 128
    assert entity.hs_color == (0.0, 100.0)
    assert entity.available
    co._apply_report("fixture", {"d52": 700})
    assert entity.brightness == 178
    assert len(co.listeners) == 1
    for remove in entity.remove_callbacks:
        remove()
    assert not co.listeners


def test_sparse_shared_record_cannot_replace_explicit_owning_family():
    client = _load_module("client")
    api = client.LeproApi.__new__(client.LeproApi)
    api._request = AsyncMock(
        side_effect=[
            {"list": [{"fid": "owner"}, {"fid": "shared"}]},
            {
                "list": [
                    {
                        "did": "fixture",
                        "type": 1,
                        "control": 2,
                        "series": "E1-30",
                        "fid": "owner",
                    }
                ]
            },
            {"list": [{"did": "fixture"}]},
            {"list": []},
        ]
    )

    async def discover_and_get_scenes():
        devices = await api.async_devices()
        await api.async_device_scenes(devices[0])
        return devices[0]

    found = asyncio.run(discover_and_get_scenes())
    assert found["fid"] == "owner"
    assert found["_family_ids"] == ["owner", "shared"]
    assert "/fid/owner/did/fixture/" in api._request.call_args.args[1]


def test_explicit_owning_family_change_is_not_treated_as_sparse_metadata():
    client = _load_module("client")
    api = client.LeproApi.__new__(client.LeproApi)
    api._request = AsyncMock(
        side_effect=[
            {"list": [{"fid": "old"}, {"fid": "new"}]},
            {
                "list": [
                    {
                        "did": "fixture",
                        "type": 1,
                        "control": 2,
                        "series": "E1-30",
                        "fid": "old",
                    }
                ]
            },
            {"list": [{"did": "fixture", "fid": "new"}]},
        ]
    )
    devices = asyncio.run(api.async_devices())
    assert devices[0]["fid"] == "new"


def test_shared_discovery_uses_selected_context_instead_of_foreign_owner():
    client = _load_module("client")
    api = client.LeproApi.__new__(client.LeproApi)
    api._request = AsyncMock(
        side_effect=[
            {"list": [{"fid": "shared-context"}]},
            {
                "list": [
                    {
                        "did": "fixture",
                        "type": 1,
                        "control": 2,
                        "series": "E1-30",
                        "fid": "foreign-owner",
                    }
                ]
            },
            {"list": []},
        ]
    )

    async def run():
        devices = await api.async_devices()
        await api.async_device_scenes(devices[0])
        return devices[0]

    found = asyncio.run(run())
    assert found["fid"] == "foreign-owner"
    assert found["_family_ids"] == ["shared-context"]
    assert "/fid/shared-context/did/fixture/" in api._request.call_args.args[1]


def test_scene_refresh_queries_each_discovered_context_and_preserves_each_cache():
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    calls = []
    failure = set()

    async def collect(device):
        fid = device["_family_ids"][0]
        calls.append(fid)
        if fid in failure:
            raise client.LeproApiError("fixture outage")
        return [{"cid": 1 if fid == "one" else 2, "name": fid}]

    co._collect_scene_pages = collect
    device = {"did": "fixture", "fid": "foreign-owner", "_family_ids": ["one", "two"]}
    assert len(asyncio.run(co._async_device_scenes(device))) == 2
    assert calls == ["one", "two"]
    failure.add("one")
    assert len(asyncio.run(co._async_device_scenes(device))) == 2


def test_denied_scene_context_does_not_erase_other_contexts():
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)

    async def collect(device):
        if device["_family_ids"] == ["denied"]:
            raise client.LeproResponseError("fixture denied", code=-904)
        return [{"cid": 2, "name": "Allowed", "_family_id": "allowed"}]

    co._collect_scene_pages = collect
    device = {"did": "fixture", "_family_ids": ["denied", "allowed"]}
    assert asyncio.run(co._async_device_scenes(device)) == [
        {"cid": 2, "name": "Allowed", "_family_id": "allowed"}
    ]


def test_first_scene_context_outage_does_not_prevent_other_context_discovery():
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)

    async def collect(device):
        if device["_family_ids"] == ["unavailable"]:
            raise client.LeproApiError("fixture outage")
        return [{"cid": 2, "name": "Available", "_family_id": "available"}]

    co._collect_scene_pages = collect
    device = {"did": "fixture", "_family_ids": ["unavailable", "available"]}
    assert asyncio.run(co._async_device_scenes(device)) == [
        {"cid": 2, "name": "Available", "_family_id": "available"}
    ]


def test_auth_failure_in_scene_context_is_not_hidden_as_optional_scene_outage():
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)

    async def collect(device):
        raise client.LeproAuthError("fixture expired")

    co._collect_scene_pages = collect
    with pytest.raises(client.LeproAuthError):
        asyncio.run(
            co._async_device_scenes({"did": "fixture", "_family_ids": ["one", "two"]})
        )


def test_removed_family_context_cache_is_discarded_after_successful_refresh():
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co._family_scene_cache = {("fixture", "removed"): [{"cid": 1, "name": "Removed"}]}

    async def collect(device):
        return [{"cid": 2, "name": "Current", "_family_id": "current"}]

    co._collect_scene_pages = collect
    result = asyncio.run(
        co._async_device_scenes({"did": "fixture", "_family_ids": ["current"]})
    )
    assert result == [{"cid": 2, "name": "Current", "_family_id": "current"}]
    assert ("fixture", "removed") not in co._family_scene_cache


def test_distinct_same_cursor_scenes_from_two_families_are_not_overwritten():
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)

    async def collect(device):
        return [{"cid": 1, "name": device["_family_ids"][0]}]

    co._collect_scene_pages = collect
    scenes = asyncio.run(
        co._async_device_scenes({"did": "fixture", "_family_ids": ["one", "two"]})
    )
    assert {scene["name"] for scene in scenes} == {"one", "two"}


def test_identical_catalog_scene_from_two_families_is_not_duplicated():
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)

    async def collect(device):
        return [{"cid": 1, "name": "Same preset"}]

    co._collect_scene_pages = collect
    scenes = asyncio.run(
        co._async_device_scenes({"did": "fixture", "_family_ids": ["one", "two"]})
    )
    assert len(scenes) == 1
