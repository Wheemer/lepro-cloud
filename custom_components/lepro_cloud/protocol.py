"""Protocol helpers for Lepro Cloud MQTT datapoints."""

from __future__ import annotations

import colorsys
import re
from collections.abc import Collection, Mapping
from random import randrange
from typing import Any

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

MIN_BRIGHTNESS = 10
MAX_BRIGHTNESS = 1000
MIN_HA_KELVIN = 2700
MAX_HA_KELVIN = 6500
MAX_COLOR_VALUE = 1000
HSV_HEX_RE = re.compile(r"^[0-9a-f]{12}$", re.IGNORECASE)

SUBSCRIBE_SUFFIXES = ("rpt", "getr", "setr", "dsr/app/getr")
MQTT_TOPIC_PREFIX = "le"

# Product-series state lists observed in MqttConnectionPool in the Android app.
RGBIC_SERIES = frozenset(
    {
        "N1-3",
        "N1-5",
        "N1-6",
        "N1-10",
        "N1-PRO-3",
        "N1-PRO-6",
        "N1-PRO-10",
        "T1",
        "S1-5",
        "S1-10",
        "S1-15",
        "S1-20",
        "S1-30",
        "S1-PRO-5",
        "S1-PRO-10",
        "S1-PRO-15",
        "S1-PRO-20",
        "S1-PRO-30",
        "STV1",
        "ZB1",
        "PG1",
    }
)
RGBIC_LENGTH_SERIES = frozenset(
    {
        "WL1",
        "E1-30",
        "E1-60",
        "E1-90",
        "E1-PLUS-30",
        "E1-PLUS-60",
        "E1-PLUS-90",
        "E1-PLUS-120",
        "E1-PLUS-180",
        "EE1-30",
        "EE1-60",
        "EE1-90",
        "EE1-120",
        "EE1-180",
        "S2-5",
        "S2-10",
        "S2-15",
        "S2-20",
        "S2-30",
        "SW1-5",
        "SW1-6",
        "SW1-10",
        "SW1-15",
        "SW1-20",
        "SW1-30",
    }
)
# Table lamps use the same RGBIC state datapoints, but their d50 payloads
# may contain multipart, product-specific patterns supplied by the app.
RGBIC_MULTIPART_SCENE_SERIES = frozenset({"TB1", "TB1-PRO"})
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
# STV1 uses normal RGBIC state plus two user-configurable TV-strip settings.
STV_STATE_DATAPOINTS = RGBIC_STATE_DATAPOINTS + ("d157", "d172")
# P1 has two APK query paths: the plug UI requests d1/d100/d101/d102,
# while the MQTT connection pool also requests d4/d5. Query their union.
PLUG_STATE_DATAPOINTS = (DP_ONLINE, DP_ON, "d100", "d101", "d102", "d4", "d5")


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


def state_datapoints_for_series(
    series: Any, extra_datapoints: Collection[str] = ()
) -> tuple[str, ...]:
    """Return the APK's MQTT state query list for a product series."""
    name = str(series or "").upper()
    if name == "P1":
        datapoints = PLUG_STATE_DATAPOINTS
    elif name in RGBIC_LENGTH_SERIES:
        datapoints = RGBIC_LENGTH_STATE_DATAPOINTS
    elif name == "STV1":
        datapoints = STV_STATE_DATAPOINTS
    elif name in RGBIC_MULTIPART_SCENE_SERIES or name in RGBIC_SERIES:
        datapoints = RGBIC_STATE_DATAPOINTS
    else:
        datapoints = BULB_STATE_DATAPOINTS
    return tuple(dict.fromkeys((*datapoints, *extra_datapoints)))


def is_complete_standard_state(state: Mapping[str, Any]) -> bool:
    """Return whether a reply is the app's complete standard light status.

    The official app treats this five-datapoint reply as proof that the device
    is online even when the broker omits the separately requested online
    value. This is deliberately narrower than treating every report as proof
    of connectivity.
    """
    return {DP_ON, DP_WORK_MODE, DP_BRIGHTNESS, DP_TEMPERATURE, DP_COLOR}.issubset(
        state
    )


def make_get_payload(
    datapoints: tuple[str, ...] = BULB_STATE_DATAPOINTS,
) -> dict[str, Any]:
    """Build the product-specific state request used by the Android app."""
    return {"id": randrange(1_000_000_000), "d": list(datapoints)}


def make_set_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    """Build a state set payload."""
    return {"id": randrange(1_000_000_000), "d": dict(values)}


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


def ha_to_lepro_brightness(
    ha_brightness: Any, *, effect: bool = False, series: str = "", firmware: str = ""
) -> int:
    """Convert Home Assistant 0..255 brightness to Lepro 1..1000."""
    try:
        value = int(ha_brightness)
    except (TypeError, ValueError):
        value = 255
    level = round((max(0, min(255, value)) / 255) * MAX_BRIGHTNESS)
    return device_brightness(level, effect=effect, series=series, firmware=firmware)


def device_brightness(
    level: int, *, effect: bool = False, series: str = "", firmware: str = ""
) -> int:
    """DeviceExtKt.bright, applied once to an app-scale value."""
    if series.upper() == "S1-10" and firmware == "2.0.16":
        level = int(level * 0.89)
    return max(100 if effect else MIN_BRIGHTNESS, min(1000, level))


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
    return round(
        ((value - MIN_HA_KELVIN) / (MAX_HA_KELVIN - MIN_HA_KELVIN)) * MAX_COLOR_VALUE
    )


def lepro_temperature_to_kelvin(value: Any) -> int | None:
    """Convert Lepro d4 0..1000 to HA Kelvin."""
    try:
        temperature = int(value)
    except (TypeError, ValueError):
        return None
    temperature = max(0, min(MAX_COLOR_VALUE, temperature))
    return round(
        MIN_HA_KELVIN
        + ((temperature / MAX_COLOR_VALUE) * (MAX_HA_KELVIN - MIN_HA_KELVIN))
    )


def color_payload(hs_color: tuple[float, float], ha_brightness: Any) -> dict[str, Any]:
    """Build the app's DpColourValue command (d2 plus HSV d5)."""
    brightness = ha_to_lepro_brightness(ha_brightness)
    return {
        DP_WORK_MODE: WORK_MODE_COLOR,
        DP_COLOR: hs_to_lepro_hsv(hs_color, brightness),
    }


def rgbic_colour_payload(
    hs_color: tuple[float, float], brightness: int, length: int, *, floor: bool = False
) -> dict[str, Any]:
    """Build a single-colour pattern checked against the APK native encoders."""
    if (
        isinstance(length, bool)
        or not isinstance(length, int)
        or not 1 <= length <= 65535
    ):
        raise ValueError("RGBIC light length is unavailable or invalid")
    hue, saturation = hs_color
    rgb = colorsys.hsv_to_rgb(
        float(hue) % 360 / 360, max(0.0, min(100.0, float(saturation))) / 100, 1.0
    )
    colour = "".join(f"{int(channel * 255 + 0.5):02X}" for channel in rgb)
    return {
        DP_WORK_MODE: WORK_MODE_SCENE,
        "d50": (
            f"T01:M05P50001{colour}{length:04X}L0010R0000S0000T0000;"
            if floor
            else f"N01:P10001{colour}F210001{length:04X}U3V3000640000E1;"
        ),
        DP_RGBIC_BRIGHTNESS: brightness,
    }


def parse_rgbic_solid(value: Any) -> tuple[tuple[float, float], int] | None:
    """Decode only the native encoder's complete single-colour RGB solid form."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"N01:P10001([0-9A-Fa-f]{6})F210001([0-9A-Fa-f]{4})U3V3000640000E1;",
        value,
    )
    if match is None:
        match = re.fullmatch(
            r"T01:M05P50001([0-9A-Fa-f]{6})([0-9A-Fa-f]{4})L[01]{4}R0000S0000T[0-9A-Fa-f]{2}00;",
            value,
        )
    if match is None or (length := int(match[2], 16)) == 0:
        return None
    rgb = tuple(int(match[1][i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue, saturation, _value = colorsys.rgb_to_hsv(*rgb)
    return (round(hue * 360, 3), round(saturation * 100, 3)), length


def rgbic_white_payload(kelvin: int, brightness: int, length: int) -> dict[str, Any]:
    """Encode the native P4 warm/cold axis; HA Kelvin is a UI mapping."""
    if (
        isinstance(length, bool)
        or not isinstance(length, int)
        or not 1 <= length <= 65535
    ):
        raise ValueError("RGBIC light length is unavailable or invalid")
    temperature = round(kelvin_to_lepro_temperature(kelvin) * 255 / 1000)
    return {
        DP_WORK_MODE: WORK_MODE_SCENE,
        DP_RGBIC_BRIGHTNESS: brightness,
        "d50": f"N01:P40001FF{temperature:02X}F210001{length:04X}U3V3000640000E1;",
    }


def parse_rgbic_white(value: Any) -> tuple[int, int] | None:
    """Decode a single P4 white group, retaining its native warm/cold axis."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"N01:P40001[0-9A-Fa-f]{2}([0-9A-Fa-f]{2})F210001([0-9A-Fa-f]{4})U3V3000640000E1;",
        value,
    )
    if match is None or (length := int(match[2], 16)) == 0:
        return None
    kelvin = round(
        MIN_HA_KELVIN + int(match[1], 16) / 255 * (MAX_HA_KELVIN - MIN_HA_KELVIN)
    )
    return kelvin, length


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
    if hsv[0] > 360 or any(part > MAX_COLOR_VALUE for part in hsv[1:]):
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
    brightness = max(1, min(MAX_BRIGHTNESS, brightness))
    return max(1, round((brightness / MAX_BRIGHTNESS) * 255))


def state_is_on(state: Mapping[str, Any]) -> bool | None:
    """Return on/off state from a Lepro state dictionary."""
    if DP_ON not in state:
        return None
    try:
        return int(state[DP_ON]) > 0
    except (TypeError, ValueError):
        return None


def scene_brightness(value: str, brightness: int) -> str:
    """Rewrite Dp6Scene units using the APK's white-versus-HSV rule."""
    if not re.fullmatch(
        r"[A-Za-z0-9_]{2}[0-9a-fA-F]{8}(?:[A-Za-z0-9_]{2}[0-9a-fA-F]{20})+", value
    ):
        raise ValueError("Invalid Lepro d6 scene")
    units = []
    for start in range(10, len(value), 22):
        unit = value[start : start + 22]
        if int(unit[2:14], 16) == 0:
            unit = f"{unit[:14]}{brightness:04X}{unit[18:]}"
        else:
            unit = f"{unit[:10]}{brightness:04X}{unit[14:]}"
        units.append(unit)
    return value[:10] + "".join(units)


def infer_report(
    state: Mapping[str, Any], *, get_response: bool = False
) -> dict[str, Any]:
    """Merge APK report inference without ever generating a command."""
    result = dict(state)
    if DP_ONLINE in result:
        return result
    keys = set(result)
    if get_response or keys & {"d1", "d2", "d50", "d52", "d102"}:
        result[DP_ONLINE] = 1
    if "d1" not in result and keys & {"d2", "d50", "d52"}:
        result[DP_ON] = 1
    return result
