"""Palette routing and light lengths traced from Lepro Home 1.0.9.269.

SmartCommonLightActivity.F5; PaletteRgbcwFragment.q1/c1;
DiyBaseFragment.initView; PaletteDiyStarFragment.u1.
These describe app commands, not a claim of physical-device verification.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# AIOTSeriesType.S2PaletteList. These enter PaletteRgbcwFragment, whose RGB
# page uses native patterns and whose white page uses DpTempValue.
CCT_STRIP_SERIES = frozenset(
    {
        "S2-5",
        "S2-10",
        "S2-15",
        "S2-20",
        "S2-30",
        "S2-PRO-5",
        "S2-PRO-10",
        "S2-PRO-20",
        "SW1-5",
        "SW1-6",
        "SW1-10",
        "SW1-15",
        "SW1-20",
        "SW1-30",
    }
)
NATIVE_RGB_PICKERS = frozenset({"diy", "diy2", "diyEaves", "diyStar", "diyMusic"})
STV_LENGTHS = {111: 36, 112: 50, 143: 48, 144: 68, 158: 24}
NATIVE_RGB_CW_SERIES = frozenset({"O1", "OE1", "OE1-PRO", "T1", "PG1"})

# icNum defaults in DiyBaseFragment. TB1's RGB palette instead sums its
# explicitly weighted StarView units; using the 48 selectable cells is wrong.
NATIVE_LENGTHS = {
    "E1-30": 30,
    "E1-60": 60,
    "E1-90": 90,
    "E1-PLUS-120": 120,
    "E1-PLUS-180": 180,
    "E1-PLUS-30": 30,
    "E1-PLUS-60": 60,
    "E1-PLUS-90": 90,
    "EE1-120": 120,
    "EE1-180": 180,
    "EE1-30": 30,
    "EE1-60": 60,
    "EE1-90": 90,
    "N1-10": 160,
    "N1-3": 48,
    "N1-5": 80,
    "N1-6": 96,
    "N1-PRO-10": 160,
    "N1-PRO-3": 48,
    "N1-PRO-6": 96,
    "O1": 182,
    "OE1": 14,
    "OE1-PRO": 14,
    "PG1": 4,
    "S1-10": 50,
    "S1-15": 75,
    "S1-20": 100,
    "S1-30": 75,
    "S1-5": 25,
    "S1-PRO-10": 50,
    "S1-PRO-15": 75,
    "S1-PRO-20": 100,
    "S1-PRO-30": 75,
    "S1-PRO-5": 25,
    "S2-10": 40,
    "S2-15": 60,
    "S2-20": 80,
    "S2-30": 120,
    "S2-5": 20,
    "S2-PRO-10": 40,
    "S2-PRO-20": 80,
    "S2-PRO-5": 20,
    "SW1-10": 30,
    "SW1-15": 45,
    "SW1-20": 60,
    "SW1-30": 90,
    "SW1-5": 15,
    "SW1-6": 24,
    "T1": 32,
    "TB1": 196,
    "TB1-PRO": 196,
    "TB2": 152,
    "WL1": 9,
    "ZB1": 15,
}


def resolved_picker(
    device: Mapping[str, Any], configs: Iterable[Mapping[str, Any]]
) -> str | None:
    picker = device.get("_color_picker")
    series = str(device.get("series") or device.get("pid") or "").upper()
    fallback = next(
        (
            str(item["colorPicker"])
            for item in configs
            if str(item.get("series", "")).upper() == series
            and isinstance(item.get("colorPicker"), str)
        ),
        None,
    )
    # An empty UI selector is not evidence that known colour hardware lost
    # its channels. SmartCommonLightActivity.F5's default is RGBcw, not a
    # power-only/dimmer palette. Retain the known native route for that model.
    if isinstance(picker, str) and (picker or not fallback):
        return picker
    return fallback


def uses_native_rgb(series: str, picker: str | None) -> bool:
    return (
        picker in NATIVE_RGB_PICKERS
        or (picker == "rgbcw" and series.upper() in NATIVE_RGB_CW_SERIES)
        or (picker == "diyString" and series.upper() == "ZB1")
        or (picker == "rgb" and series.upper() == "STV1")
    )


def has_native_cct(series: str, picker: str | None) -> bool:
    series = series.upper()
    if uses_pattern_cct(series, picker):
        return True
    return (
        picker == "rgbcw"
        or picker == "diyString"
        or (picker == "diy2" and series in CCT_STRIP_SERIES)
        or (series == "F2-30" and picker == "rgb")
    )


def uses_pattern_cct(series: str, picker: str | None) -> bool:
    # EE1 routes to PaletteDoodle2Fragment; E1/Plus and PG1 route to the
    # RGB + warm/cold PaletteDIYEStringFragment (native lightMode=3).
    return (series.upper() == "PG1" and picker == "rgbcw") or (
        picker == "diyEaves" and not series.upper().startswith("EE1-")
    )


def pattern_length(device: Mapping[str, Any], state: Mapping[str, Any]) -> int:
    series = str(device.get("series") or device.get("pid") or "").upper()
    if series == "STV1":
        try:
            return STV_LENGTHS.get(int(device.get("proId") or 0), 36)
        except (ValueError, TypeError):
            return 36
    if series in {"TB1", "TB1-PRO"}:
        return NATIVE_LENGTHS[series]
    reported = state.get("d53")
    reports_length = (
        series.startswith(("E1-", "EE1-"))
        or series in CCT_STRIP_SERIES
        or series in {"WL1", "ZB1", "PG1"}
    )
    if (
        reports_length
        and isinstance(reported, int)
        and not isinstance(reported, bool)
        and 1 <= reported <= 65535
        and (series != "PG1" or reported <= 4)
    ):
        return reported
    if series == "SW1-6" and str(device.get("proId")) == "154":
        return 18
    # PaletteDIYStringFragment.F2 uses 15 when E1/E1-Plus reports zero length.
    if series.startswith(("E1-",)):
        return 15
    return NATIVE_LENGTHS.get(series, 48)
