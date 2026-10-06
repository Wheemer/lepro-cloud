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
DP_RGBIC_BRIGHTNESS = "d52"
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
HSV_HEX_RE = re.compile(r"^[0-9a-f]{12}$", re.IGNORECASE)

SUBSCRIBE_SUFFIXES = ("rpt", "getr", "setr")
MQTT_TOPIC_PREFIX = "le"

# Product-series state lists observed in MqttConnectionPool in the Android app.
RGBIC_SERIES = frozenset(
    {
        "N1-3", "N1-5", "N1-6", "N1-10", "N1-PRO-3", "N1-PRO-6", "N1-PRO-10",
        "T1", "S1-5", "S1-10", "S1-15", "S1-20", "S1-30", "S1-PRO-5",
        "S1-PRO-10", "S1-PRO-15", "S1-PRO-20", "S1-PRO-30", "STV1", "ZB1", "PG1",
    }
)
RGBIC_LENGTH_SERIES = frozenset(
    {
        "WL1", "E1-30", "E1-60", "E1-90", "E1-PLUS-30", "E1-PLUS-60",
        "E1-PLUS-90", "E1-PLUS-120", "E1-PLUS-180", "EE1-30", "EE1-60", "EE1-90",
        "EE1-120", "EE1-180", "S2-5", "S2-10", "S2-15", "S2-20", "S2-30",
        "SW1-5", "SW1-6", "SW1-10", "SW1-15", "SW1-20", "SW1-30",
    }
)
BULB_STATE_DATAPOINTS = (
    DP_ONLINE,
    DP_ON,
    DP_WORK_MODE,
    DP_BRIGHTNESS,
    DP_TEMPERATURE,
    DP_COLOR,
)
RGBIC_STATE_DATAPOINTS = BULB_STATE_DATAPOINTS + ("d50", DP_RGBIC_BRIGHTNESS)
RGBIC_LENGTH_STATE_DATAPOINTS = RGBIC_STATE_DATAPOINTS + ("d53",)
PLUG_STATE_DATAPOINTS = (DP_ONLINE, DP_ON, "d100", "d101", "d102")


def topic_get(device_id: str) -> str:
    """Return the Lepro property-get topic for a device."""
    return f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/get"


def topic_set(device_id: str) -> str:
    """Return the Lepro property-set topic for a device."""
    return f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/set"


def subscription_topics(device_id: str) -> tuple[str, ...]:
    """Return the response/report topics used by Wi-Fi lights and plugs."""
    return tuple(
        f"{MQTT_TOPIC_PREFIX}/{device_id}/prp/{suffix}" for suffix in SUBSCRIBE_SUFFIXES
    )


def state_datapoints_for_series(series: Any) -> tuple[str, ...]:
    """Return the APK's MQTT state query list for a product series."""
    name = str(series or "").upper()
    if name == "P1":
        return PLUG_STATE_DATAPOINTS
    if name in RGBIC_LENGTH_SERIES:
        return RGBIC_LENGTH_STATE_DATAPOINTS
    if name in RGBIC_SERIES:
        return RGBIC_STATE_DATAPOINTS
    return BULB_STATE_DATAPOINTS


def make_get_payload(datapoints: tuple[str, ...] = BULB_STATE_DATAPOINTS) -> dict[str, Any]:
    """Build the product-specific state request used by the Android app."""
    return {"id": uuid4().hex, "d": list(datapoints)}



def make_set_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    """Build a state set payload."""
    return {"id": uuid4().hex, "d": dict(values)}


def on_payload(is_on: bool) -> dict[str, int]:
    """Build an on/off command using the verified d1 switch datapoint."""
    return {DP_ON: 1 if is_on else 0}


def brightness_payload(
    ha_brightness: int,
    *,
    datapoint: str = DP_BRIGHTNESS,
    work_mode: int = WORK_MODE_WHITE,
) -> dict[str, int]:
    """Build a brightness command for an ordinary or RGBIC light.

    The Android app uses ``d3`` for conventional bulbs and ``d52`` for RGBIC
    products. Both command formats carry the active work mode in ``d2``.
    """
    return {
        DP_WORK_MODE: work_mode,
        datapoint: ha_to_lepro_brightness(ha_brightness),
    }


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
    """Build the app's DpColourValue command (d2 plus HSV d5)."""
    brightness = ha_to_lepro_brightness(ha_brightness)
    return {
        DP_WORK_MODE: WORK_MODE_COLOR,
        DP_COLOR: hs_to_lepro_hsv(hs_color, brightness),
    }


def hs_to_lepro_hsv(hs_color: tuple[float, float], value: Any = MAX_COLOR_VALUE) -> str:
    """Convert HA HS color to Lepro's 12-digit uppercase HSV hex string."""
    hue, saturation = hs_color
    hsv = (
        round(max(0.0, min(360.0, float(hue)))),
        round((max(0.0, min(100.0, float(saturation))) / 100) * MAX_COLOR_VALUE),
        max(0, min(MAX_COLOR_VALUE, int(value))),
    )
    return "".join(f"{part:04X}" for part in hsv)


def parse_lepro_hsv(value: Any) -> tuple[int, int, int] | None:
    """Parse Lepro d5 as exactly 12 hexadecimal HSV digits."""
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
