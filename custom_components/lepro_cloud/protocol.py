"""Protocol helpers for Lepro Cloud MQTT datapoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

DP_ON = "d1"
DP_WORK_MODE = "d2"
DP_BRIGHTNESS = "d3"
DP_ONLINE = "online"

WORK_MODE_WHITE = 1

MIN_BRIGHTNESS = 1
MAX_BRIGHTNESS = 1000

SUBSCRIBE_SUFFIXES = ("rpt", "getr", "setr")
MQTT_TOPIC_PREFIX = "le"


def topic_get(device_id: str) -> str:
    """Return the Lepro property-get topic for a device."""
    return f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/get"


def topic_set(device_id: str) -> str:
    """Return the Lepro property-set topic for a device."""
    return f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/set"


def subscription_topics(device_id: str) -> tuple[str, ...]:
    """Return property response/report topics used by the Android app."""
    return tuple(f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/{suffix}" for suffix in SUBSCRIBE_SUFFIXES)


def make_get_payload() -> dict[str, Any]:
    """Build a safe state request payload."""
    return {"id": uuid4().hex, "d": {}}


def make_set_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    """Build a state set payload."""
    return {"id": uuid4().hex, "d": dict(values)}


def on_payload(is_on: bool) -> dict[str, int]:
    """Build an on/off command using the verified d1 switch datapoint."""
    return {DP_ON: 1 if is_on else 0}


def brightness_payload(ha_brightness: int) -> dict[str, int]:
    """Build a brightness command using the verified d3 brightness datapoint."""
    level = round((max(0, min(255, ha_brightness)) / 255) * MAX_BRIGHTNESS)
    return {DP_WORK_MODE: WORK_MODE_WHITE, DP_BRIGHTNESS: max(MIN_BRIGHTNESS, level)}


def lepro_to_ha_brightness(value: Any) -> int | None:
    """Convert Lepro 1..1000 brightness to Home Assistant 1..255."""
    try:
        brightness = int(value)
    except (TypeError, ValueError):
        return None
    brightness = max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, brightness))
    return max(1, round((brightness / MAX_BRIGHTNESS) * 255))


def state_is_on(state: Mapping[str, Any]) -> bool | None:
    """Return on/off state from a Lepro state dictionary."""
    if DP_ON not in state:
        return None
    try:
        return int(state[DP_ON]) > 0
    except (TypeError, ValueError):
        return None
