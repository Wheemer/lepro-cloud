"""Regression witnesses from APK palette routing and executed native encoders.

These use import stubs, never a Home Assistant instance or vendor account.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from test_platform_devices import FakeCoordinator, FakeHass, _load_module


@pytest.mark.parametrize(
    "series,picker,length",
    [
        ("S1-5", "diy", 25),
        ("STV1", "rgb", 36),
        ("N1-3", "diy", 48),
        ("TB1", "diyStar", 196),
        ("TB1-PRO", "diyStar", 196),
        ("TB2", "diyMusic", 152),
        ("O1", "rgbcw", 182),
        ("OE1", "rgbcw", 14),
        ("T1", "rgbcw", 32),
        ("S2-5", "diy2", 20),
        ("E1-30", "diyEaves", 30),
    ],
)
def test_rgb_command_uses_apk_palette_and_native_length(series, picker, length):
    light = _load_module("light")
    coordinator = FakeCoordinator()
    coordinator.states["light-1"] = {"d2": 2}
    if series == "E1-30":
        coordinator.states["light-1"]["d53"] = 30
    entity = light.LeproCloudLight(
        coordinator, "light-1", {"type": 1, "series": series, "_color_picker": picker}
    )
    entity.hass = FakeHass()
    asyncio.run(entity.async_turn_on(hs_color=(120, 100), brightness=255))
    payload = coordinator.commands[-1][1]
    assert payload["d2"] == 2 and payload["d52"] == 1000
    assert "d5" not in payload
    expected = (
        "T01:M05P5000100FF0000B6L0010R0000S0000T0000;"
        if series == "O1"
        else f"N01:P1000100FF00F210001{length:04X}U3V3000640000E1;"
    )
    assert payload["d50"] == expected


@pytest.mark.parametrize(
    "series,picker,white",
    [
        ("S2-5", "diy2", True),
        ("SW1-5", "diy2", True),
        ("SW1-6", "diy2", True),
        ("ZB1", "diyString", True),
        ("F2-30", "rgb", True),
        ("PG1", "rgbcw", True),
        ("E1-30", "diyEaves", True),
        ("EE1-30", "diyEaves", False),
        ("TB1", "diyStar", False),
        ("S1-5", "diy", False),
    ],
)
def test_white_support_follows_actual_palette_children(series, picker, white):
    light = _load_module("light")
    entity = light.LeproCloudLight(
        FakeCoordinator(),
        "light-1",
        {"type": 1, "series": series, "_color_picker": picker},
    )
    assert ("color_temp" in entity.supported_color_modes) is white
    assert "hs" in entity.supported_color_modes


def test_native_patterns_match_independent_apk_encoder_and_decoder_witnesses():
    protocol = _load_module("protocol")
    evidence = json.loads(
        (Path(__file__).parent / "fixtures/apk-native-patterns.json").read_text()
    )
    assert len(evidence["library_sha256"]) == 64
    hs = {
        0xFFFF0000: (0, 100),
        0xFF00FF00: (120, 100),
        0xFF0000FF: (240, 100),
        0xFFFFFFFF: (0, 0),
    }
    for row in evidence["fixtures"]:
        if row["mode"] == 1:
            payload = protocol.rgbic_colour_payload(
                hs[row["colour"]], 1000, row["length"]
            )
            assert payload["d50"] == row["payload"]
            assert row["decoded"]["colours"] == [row["colour"]]
            assert row["decoded"]["lengths"] == [row["length"]]
            assert protocol.parse_rgbic_solid(row["payload"])[1] == row["length"]
        elif row["mode"] == 4:
            assert row["decoded"]["arguments"][:6] == [
                0,
                2,
                0,
                [0xFF00FF00],
                [182],
                182,
            ]
            assert (
                protocol.rgbic_colour_payload((120, 100), 1000, 182, floor=True)["d50"]
                == row["payload"]
            )
        elif row["colour"] in (0xFFFFA657, 0xFFFFFFFF):
            kelvin = 2700 if row["colour"] == 0xFFFFA657 else 6500
            assert (
                protocol.rgbic_white_payload(kelvin, 1000, 30)["d50"] == row["payload"]
            )
            assert protocol.parse_rgbic_white(row["payload"]) == (kelvin, 30)


def test_native_white_command_and_stale_white_pattern_mode():
    light = _load_module("light")
    coordinator = FakeCoordinator()
    coordinator.states["light-1"] = {"d2": 2, "d53": 30}
    entity = light.LeproCloudLight(
        coordinator,
        "light-1",
        {"type": 1, "series": "E1-30", "_color_picker": "diyEaves"},
    )
    entity.hass = FakeHass()
    asyncio.run(entity.async_turn_on(color_temp_kelvin=2700, brightness=255))
    value = coordinator.commands[-1][1]
    assert value["d50"] == "N01:P40001FF00F210001001EU3V3000640000E1;"
    coordinator.states["light-1"].update(value)
    assert entity.color_mode == "color_temp"
    assert entity.color_temp_kelvin == 2700
    coordinator.states["light-1"]["d2"] = 1
    assert entity.color_mode == "hs"


def test_fixed_native_lengths_do_not_take_unrelated_d53():
    profiles = _load_module("capabilities")
    assert profiles.pattern_length({"series": "TB1"}, {"d53": 48}) == 196
    assert profiles.pattern_length({"series": "O1"}, {"d53": 999}) == 182
    assert profiles.pattern_length({"series": "TB2"}, {"d53": 999}) == 152
    assert profiles.pattern_length({"series": "SW1-6", "proId": 154}, {"d53": 21}) == 21
    assert profiles.pattern_length({"series": "E1-30"}, {"d53": 0}) == 15
    assert profiles.pattern_length({"series": "SW1-6", "proId": 154}, {}) == 18


def test_saved_scene_outer_fallback_and_numeric_datapoints():
    scenes = _load_module("scenes")
    fallback = {"d5": {"dp": "d5", "res": "007801F403E8"}}
    assert scenes.selected_effect(fallback, "striplight") == ("d5", "007801F403E8")
    assert scenes.selected_effect(
        {"smartbulb": {"dp": "d3", "res": ""}}, "smartbulb"
    ) == ("d3", "")
    assert scenes.selected_effect(
        {"smartbulb": {"dp": "d52", "res": ""}}, "smartbulb"
    ) == ("d52", "")
    assert (
        scenes.selected_effect({"d5": {"dp": "d5", "res": "bad"}}, "smartbulb") is None
    )


def test_selecting_d6_keeps_unit_brightness_until_explicit_dimming():
    light = _load_module("light")
    coordinator = FakeCoordinator()
    value = "000032006401007803E801F600000000"
    entity = light.LeproCloudLight(
        coordinator,
        "light-1",
        {
            "type": 1,
            "series": "B1",
            "scenes": [{"name": "Saved", "smartbulb": {"dp": "d6", "res": value}}],
        },
    )
    entity.hass = FakeHass()
    asyncio.run(entity.async_turn_on(effect="Saved"))
    assert coordinator.commands[-1][1]["d6"] == value
    asyncio.run(entity.async_turn_on(effect="Saved", brightness=255))
    assert coordinator.commands[-1][1]["d6"] == "000032006401007803E803E800000000"


def test_recovery_queries_same_native_fields_as_initial_connect():
    client = _load_module("client")
    coordinator = client.LeproCoordinator.__new__(client.LeproCoordinator)
    coordinator.effect_types = {}
    points = coordinator._state_query_datapoints(
        {"series": "TB2", "_color_picker": "diyMusic"}
    )
    assert {"d50", "d52", "d53"} <= set(points)


@pytest.mark.parametrize(
    "dp,res,expected",
    [
        ("d5", "007801F403E8", "007801F403E8"),
        ("d3", "", 1000),
        ("d52", "", 1000),
    ],
)
def test_saved_scene_writer_matches_aiotutils_dispatch(dp, res, expected):
    light = _load_module("light")
    coordinator = FakeCoordinator()
    entity = light.LeproCloudLight(
        coordinator,
        "light-1",
        {
            "type": 1,
            "series": "B1",
            "scenes": [{"name": "Saved", "smartbulb": {"dp": dp, "res": res}}],
        },
    )
    entity.hass = FakeHass()
    asyncio.run(entity.async_turn_on(effect="Saved", brightness=255))
    assert coordinator.commands[-1][1] == {"d1": 1, "d2": 2, dp: expected}
    assert coordinator.states == {}


def test_ordinary_music_brightness_does_not_send_untraced_rgbic_command():
    light = _load_module("light")
    coordinator = FakeCoordinator()
    coordinator.states["light-1"] = {"d2": 3, "d3": 500}
    entity = light.LeproCloudLight(coordinator, "light-1", {"type": 1, "series": "B1"})
    entity.hass = FakeHass()
    with pytest.raises(ValueError, match="music mode"):
        asyncio.run(entity.async_turn_on(brightness=128))
    assert not coordinator.commands


def test_native_model_exceptions_only_apply_on_their_actual_picker_route():
    profiles = _load_module("capabilities")
    assert profiles.uses_pattern_cct("PG1", "rgbcw")
    assert not profiles.uses_pattern_cct("PG1", "")
    assert profiles.uses_native_rgb("ZB1", "diyString")
    assert not profiles.uses_native_rgb("unknown", "diyString")


@pytest.mark.parametrize(
    "pid,length", [(111, 36), (112, 50), (143, 48), (144, 68), (158, 24), (0, 36)]
)
def test_tv_native_length_uses_apk_product_id_mapping(pid, length):
    profiles = _load_module("capabilities")
    assert (
        profiles.pattern_length({"series": "STV1", "proId": pid}, {"d53": 999})
        == length
    )
