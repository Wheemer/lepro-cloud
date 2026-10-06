"""Tests for clean-room Lepro protocol helpers."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_PROTOCOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "lepro_cloud"
    / "protocol.py"
)
_SPEC = spec_from_file_location("lepro_cloud_protocol", _PROTOCOL_PATH)
assert _SPEC and _SPEC.loader
protocol = module_from_spec(_SPEC)
_SPEC.loader.exec_module(protocol)

DP_BRIGHTNESS = protocol.DP_BRIGHTNESS
DP_RGBIC_BRIGHTNESS = protocol.DP_RGBIC_BRIGHTNESS
DP_COLOR = protocol.DP_COLOR
DP_ON = protocol.DP_ON
DP_TEMPERATURE = protocol.DP_TEMPERATURE
DP_WORK_MODE = protocol.DP_WORK_MODE
WORK_MODE_COLOR = protocol.WORK_MODE_COLOR
WORK_MODE_WHITE = protocol.WORK_MODE_WHITE
brightness_payload = protocol.brightness_payload
color_payload = protocol.color_payload
kelvin_to_lepro_temperature = protocol.kelvin_to_lepro_temperature
lepro_to_ha_brightness = protocol.lepro_to_ha_brightness
lepro_hsv_to_hs = protocol.lepro_hsv_to_hs
lepro_hsv_to_rgb = protocol.lepro_hsv_to_rgb
lepro_temperature_to_kelvin = protocol.lepro_temperature_to_kelvin
on_payload = protocol.on_payload
parse_lepro_hsv = protocol.parse_lepro_hsv
rgb_to_hs = protocol.rgb_to_hs
hs_to_lepro_hsv = protocol.hs_to_lepro_hsv
state_is_on = protocol.state_is_on
state_datapoints_for_series = protocol.state_datapoints_for_series
subscription_topics = protocol.subscription_topics
topic_get = protocol.topic_get
topic_set = protocol.topic_set


def test_topics() -> None:
    assert topic_get("123") == "le/123/prp/get"
    assert topic_set("123") == "le/123/prp/set"
    assert subscription_topics("123") == (
        "le/123/prp/rpt",
        "le/123/prp/getr",
        "le/123/prp/setr",
    )


def test_state_queries_match_the_apk_product_families() -> None:
    assert state_datapoints_for_series("B3") == (
        "online", "d1", "d2", "d3", "d4", "d5"
    )
    assert state_datapoints_for_series("S1-10") == (
        "online", "d1", "d2", "d3", "d4", "d5", "d50", "d52"
    )
    assert state_datapoints_for_series("E1-60") == (
        "online", "d1", "d2", "d3", "d4", "d5", "d50", "d52", "d53"
    )
    assert state_datapoints_for_series("P1") == (
        "online", "d1", "d100", "d101", "d102"
    )
    assert state_datapoints_for_series("future-product") == (
        "online", "d1", "d2", "d3", "d4", "d5"
    )


def test_on_payload() -> None:
    assert on_payload(True) == {DP_ON: 1}
    assert on_payload(False) == {DP_ON: 0}


def test_brightness_payload_uses_verified_datapoints() -> None:
    payload = brightness_payload(128)
    assert payload[DP_WORK_MODE] == WORK_MODE_WHITE
    assert WORK_MODE_WHITE == 0
    assert payload[DP_BRIGHTNESS] == 502
    assert set(payload) == {DP_WORK_MODE, DP_BRIGHTNESS}


def test_brightness_payload_clamps() -> None:
    assert brightness_payload(-1)[DP_BRIGHTNESS] == 1
    assert brightness_payload(999)[DP_BRIGHTNESS] == 1000


def test_rgbic_brightness_payload_preserves_the_active_mode() -> None:
    assert brightness_payload(128, datapoint=DP_RGBIC_BRIGHTNESS, work_mode=2) == {
        DP_WORK_MODE: 2,
        DP_RGBIC_BRIGHTNESS: 502,
    }


def test_lepro_to_ha_brightness() -> None:
    assert lepro_to_ha_brightness(1) == 1
    assert lepro_to_ha_brightness(1000) == 255
    assert lepro_to_ha_brightness("500") == 128
    assert lepro_to_ha_brightness("bad") is None


def test_temperature_scale_maps_warm_to_cool_kelvin_range() -> None:
    assert kelvin_to_lepro_temperature(6500) == 1000
    assert kelvin_to_lepro_temperature(2700) == 0
    assert kelvin_to_lepro_temperature(4600) == 500
    assert kelvin_to_lepro_temperature(9999) == 1000
    assert kelvin_to_lepro_temperature(1) == 0
    assert lepro_temperature_to_kelvin(0) == 2700
    assert lepro_temperature_to_kelvin(1000) == 6500
    assert lepro_temperature_to_kelvin("500") == 4600
    assert lepro_temperature_to_kelvin("bad") is None


def test_hsv_hex_parsing_requires_exact_lowercase_12_digit_payload() -> None:
    assert parse_lepro_hsv("000003e803e8") == (0, 1000, 1000)
    assert parse_lepro_hsv("03e803e803e8") == (1000, 1000, 1000)
    assert parse_lepro_hsv("03E803e803e8") is None
    assert parse_lepro_hsv("03e803e803e") is None
    assert parse_lepro_hsv("03e903e803e8") is None


def test_hs_rgb_helpers_convert_lepro_hsv() -> None:
    assert hs_to_lepro_hsv((120, 50), 250) == "007801f400fa"
    assert lepro_hsv_to_hs("00b403e803e8") == (180.0, 100.0)
    assert lepro_hsv_to_rgb("000003e803e8") == (255, 0, 0)
    assert rgb_to_hs(0, 255, 0) == (120.0, 100.0)


def test_color_payload_uses_verified_datapoints() -> None:
    assert color_payload((240, 75), 128) == {
        DP_WORK_MODE: WORK_MODE_COLOR,
        DP_BRIGHTNESS: 502,
        DP_COLOR: "00f002ee01f6",
    }


def test_state_is_on() -> None:
    assert state_is_on({DP_ON: 1}) is True
    assert state_is_on({DP_ON: 0}) is False
    assert state_is_on({DP_ON: "bad"}) is None
    assert state_is_on({}) is None
