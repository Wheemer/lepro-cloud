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
DP_ON = protocol.DP_ON
DP_WORK_MODE = protocol.DP_WORK_MODE
WORK_MODE_WHITE = protocol.WORK_MODE_WHITE
brightness_payload = protocol.brightness_payload
lepro_to_ha_brightness = protocol.lepro_to_ha_brightness
on_payload = protocol.on_payload
state_is_on = protocol.state_is_on
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


def test_on_payload() -> None:
    assert on_payload(True) == {DP_ON: 1}
    assert on_payload(False) == {DP_ON: 0}


def test_brightness_payload_uses_verified_datapoints() -> None:
    payload = brightness_payload(128)
    assert payload[DP_WORK_MODE] == WORK_MODE_WHITE
    assert payload[DP_BRIGHTNESS] == 502
    assert set(payload) == {DP_WORK_MODE, DP_BRIGHTNESS}


def test_brightness_payload_clamps() -> None:
    assert brightness_payload(-1)[DP_BRIGHTNESS] == 1
    assert brightness_payload(999)[DP_BRIGHTNESS] == 1000


def test_lepro_to_ha_brightness() -> None:
    assert lepro_to_ha_brightness(1) == 1
    assert lepro_to_ha_brightness(1000) == 255
    assert lepro_to_ha_brightness("500") == 128
    assert lepro_to_ha_brightness("bad") is None


def test_state_is_on() -> None:
    assert state_is_on({DP_ON: 1}) is True
    assert state_is_on({DP_ON: 0}) is False
    assert state_is_on({DP_ON: "bad"}) is None
    assert state_is_on({}) is None
