"""Device classification helpers for Lepro Cloud discovery."""

from __future__ import annotations

import re
from typing import Any

from .protocol import parse_wire_integer

DEVICE_TYPE_LIGHT = 1
DEVICE_TYPE_PLUG = 2


def device_type(device: dict[str, Any]) -> int | None:
    """Return the verified Wi-Fi device type from a discovery payload."""
    for key in ("type", "deviceType", "devType"):
        value = device.get(key)
        if value is None:
            continue
        return parse_wire_integer(value)
    return None


def device_name(device: dict[str, Any], fallback: str = "Lepro Device") -> str:
    """Return the best display name from a discovery payload."""
    for key in ("friendlyName", "nickname", "deviceName", "devName"):
        value = device.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    inherited = device.get("_display_name")
    if isinstance(inherited, str) and inherited:
        return inherited
    for key in ("name", "mac"):
        value = device.get(key)
        if value:
            name = str(value).strip()
            # The APK displays DeviceEntity.name verbatim. An underscore and
            # four characters alone do not prove that a user name has a suffix.
            # AddDeviceNewActivity creates factory names as series_deviceSn.
            series, serial = device.get("series"), device.get("deviceSn")
            if key == "name" and series and serial and name == f"{series}_{serial}":
                return str(series)
            return name
    return fallback


def preserve_device_name(device: dict[str, Any], previous_name: str | None) -> None:
    """Retain a known friendly name when cloud discovery adds an opaque suffix."""
    device.pop("_display_name", None)
    raw = device.get("name")
    if not isinstance(raw, str) or not previous_name:
        return
    # Registry history proves the prefix; do not strip arbitrary new user names.
    if re.fullmatch(re.escape(previous_name) + r"_[A-Z0-9]{4}", raw):
        device["_display_name"] = previous_name


def is_light(device: dict[str, Any]) -> bool:
    """Return true when discovery identifies a Wi-Fi light."""
    return device_type(device) == DEVICE_TYPE_LIGHT and has_cloud_control(device)


def is_plug(device: dict[str, Any]) -> bool:
    """Return true when discovery identifies a Wi-Fi plug."""
    return device_type(device) == DEVICE_TYPE_PLUG and has_cloud_control(device)


def has_cloud_control(device: dict[str, Any]) -> bool:
    """Missing legacy metadata is tolerated; explicit BLE-only is not."""
    control = device.get("control")
    return control is None or parse_wire_integer(control) in {2, 3}


def is_supported_device(device: dict[str, Any]) -> bool:
    """Return true for a non-camera device this integration supports."""
    return is_light(device) or is_plug(device)


def device_info(
    device: dict[str, Any], device_id: str, fallback_name: str = "Lepro Device"
) -> dict[str, Any]:
    """Build Home Assistant device metadata from the app's discovery payload."""
    info: dict[str, Any] = {
        "identifiers": {("lepro_cloud", device_id)},
        "name": device_name(device, fallback_name),
        "manufacturer": "Lepro",
        "model": device.get("series") or device.get("pid") or "Wi-Fi device",
    }
    if firmware := device.get("fwVersion"):
        info["sw_version"] = str(firmware)
    if hardware := device.get("hwVersion"):
        info["hw_version"] = str(hardware)
    if mac := device.get("mac"):
        info["connections"] = {("mac", str(mac))}
    return info
