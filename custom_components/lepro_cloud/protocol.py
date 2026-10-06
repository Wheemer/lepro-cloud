"""Protocol helpers for Lepro Cloud MQTT datapoints."""

from __future__ import annotations

import colorsys
from collections.abc import Mapping
import re
from typing import Any
from uuid import uuid4

DP_ON = "d1"
DP_WORK_MODE = "d2"
DP_BRIGHTNESS = "d3"
DP_TEMPERATURE = "d4"
DP_COLOR = "d5"
DP_ONLINE = "online"

WORK_MODE_WHITE = 0
WORK_MODE_COLOR = 1
WORK_MODE_SCENE = 2
WORK_MODE_MUSIC = 3

MIN_BRIGHTNESS = 1
MAX_BRIGHTNESS = 1000
MIN_HA_KELVIN = 2700
MAX_HA_KELVIN = 6500
MAX_COLOR_VALUE = 1000
HSV_HEX_RE = re.compile(r"^[0-9a-f]{12}$")

SUBSCRIBE_SUFFIXES = ("rpt", "getr", "setr")
CAMERA_SUBSCRIBE_SUFFIXES = ("prp/rpt", "act/exer", "prp/dsr/app/getr", "prp/getr")
MQTT_TOPIC_PREFIX = "le"


def topic_get(device_id: str) -> str:
    """Return the Lepro property-get topic for a device."""
    return f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/get"


def topic_set(device_id: str) -> str:
    """Return the Lepro property-set topic for a device."""
    return f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/set"


def topic_camera_get(device_id: str) -> str:
    """Return the camera status-get topic used by the Android app."""
    return f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/dsr/app/get"


def topic_camera_execute(device_id: str) -> str:
    """Return the camera action topic used for the P2P address exchange."""
    return f"{MQTT_TOPIC_PREFIX}/{device_id}/act/exe"


def subscription_topics(device_id: str, *, is_camera: bool = False) -> tuple[str, ...]:
    """Return the exact response/report topics used by the Android app."""
    if is_camera:
        return tuple(
            f"{MQTT_TOPIC_PREFIX}/{device_id}/{suffix}"
            for suffix in CAMERA_SUBSCRIBE_SUFFIXES
        )
    return tuple(
        f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/{suffix}" for suffix in SUBSCRIBE_SUFFIXES
    )


def make_get_payload() -> dict[str, Any]:
    """Build a safe state request payload."""
    return {"id": uuid4().hex, "d": {}}


def make_camera_get_payload() -> dict[str, Any]:
    """Build the camera status request observed in the Android MQTT client."""
    return {"id": uuid4().hex, "d": [DP_ONLINE]}


def make_set_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    """Build a state set payload."""
    return {"id": uuid4().hex, "d": dict(values)}


def on_payload(is_on: bool) -> dict[str, int]:
    """Build an on/off command using the verified d1 switch datapoint."""
    return {DP_ON: 1 if is_on else 0}


def brightness_payload(ha_brightness: int) -> dict[str, int]:
    """Build a brightness command using the verified d3 brightness datapoint."""
    return {DP_WORK_MODE: WORK_MODE_WHITE, DP_BRIGHTNESS: ha_to_lepro_brightness(ha_brightness)}


def ha_to_lepro_brightness(ha_brightness: Any) -> int:
    """Convert Home Assistant 0..255 brightness to Lepro 1..1000."""
    try:
        value = int(ha_brightness)
    except (TypeError, ValueError):
        value = 255
    level = round((max(0, min(255, value)) / 255) * MAX_BRIGHTNESS)
    return max(MIN_BRIGHTNESS, level)


def white_payload(ha_brightness: Any, color_temp_kelvin: Any) -> dict[str, int]:
    """Build a white-mode command with d2, d3, and d4."""
    return {
        DP_WORK_MODE: WORK_MODE_WHITE,
        DP_BRIGHTNESS: ha_to_lepro_brightness(ha_brightness),
        DP_TEMPERATURE: kelvin_to_lepro_temperature(color_temp_kelvin),
    }


def kelvin_to_lepro_temperature(kelvin: Any) -> int:
    """Convert HA Kelvin to Lepro d4 where 0 is warm and 1000 is cool."""
    try:
        value = int(kelvin)
    except (TypeError, ValueError):
        value = MAX_HA_KELVIN
    value = max(MIN_HA_KELVIN, min(MAX_HA_KELVIN, value))
    return round(((value - MIN_HA_KELVIN) / (MAX_HA_KELVIN - MIN_HA_KELVIN)) * MAX_COLOR_VALUE)


def lepro_temperature_to_kelvin(value: Any) -> int | None:
    """Convert Lepro d4 0..1000 to HA Kelvin."""
    try:
        temperature = int(value)
    except (TypeError, ValueError):
        return None
    temperature = max(0, min(MAX_COLOR_VALUE, temperature))
    return round(MIN_HA_KELVIN + ((temperature / MAX_COLOR_VALUE) * (MAX_HA_KELVIN - MIN_HA_KELVIN)))


def color_payload(hs_color: tuple[float, float], ha_brightness: Any) -> dict[str, Any]:
    """Build a color-mode command using the verified d5 HSV datapoint."""
    brightness = ha_to_lepro_brightness(ha_brightness)
    return {
        DP_WORK_MODE: WORK_MODE_COLOR,
        DP_BRIGHTNESS: brightness,
        DP_COLOR: hs_to_lepro_hsv(hs_color, brightness),
    }


def hs_to_lepro_hsv(hs_color: tuple[float, float], value: Any = MAX_COLOR_VALUE) -> str:
    """Convert HA HS color to Lepro's 12-digit lowercase HSV hex string."""
    hue, saturation = hs_color
    hsv = (
        round(max(0.0, min(360.0, float(hue)))),
        round((max(0.0, min(100.0, float(saturation))) / 100) * MAX_COLOR_VALUE),
        max(0, min(MAX_COLOR_VALUE, int(value))),
    )
    return "".join(f"{part:04x}" for part in hsv)


def parse_lepro_hsv(value: Any) -> tuple[int, int, int] | None:
    """Parse Lepro d5 as exactly 12 lowercase HSV hex digits."""
    if not isinstance(value, str) or not HSV_HEX_RE.fullmatch(value):
        return None
    hsv = tuple(int(value[index : index + 4], 16) for index in range(0, 12, 4))
    if any(part > MAX_COLOR_VALUE for part in hsv):
        return None
    return hsv


def lepro_hsv_to_hs(value: Any) -> tuple[float, float] | None:
    """Convert Lepro d5 HSV to HA HS color."""
    hsv = parse_lepro_hsv(value)
    if hsv is None:
        return None
    hue, saturation, _brightness = hsv
    return (round(hue % 360, 3), round((saturation / MAX_COLOR_VALUE) * 100, 3))


def lepro_hsv_to_rgb(value: Any) -> tuple[int, int, int] | None:
    """Convert Lepro d5 HSV to RGB bytes."""
    hsv = parse_lepro_hsv(value)
    if hsv is None:
        return None
    hue, saturation, brightness = hsv
    red, green, blue = colorsys.hsv_to_rgb(
        ((hue % 360) / 360),
        saturation / MAX_COLOR_VALUE,
        brightness / MAX_COLOR_VALUE,
    )
    return (round(red * 255), round(green * 255), round(blue * 255))


def rgb_to_hs(red: Any, green: Any, blue: Any) -> tuple[float, float]:
    """Convert RGB bytes to HA HS color."""
    rgb = tuple(max(0, min(255, int(part))) / 255 for part in (red, green, blue))
    hue, saturation, _value = colorsys.rgb_to_hsv(*rgb)
    return (round(hue * 360, 3), round(saturation * 100, 3))


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
