"""Device classification helpers for Lepro Cloud discovery."""

from __future__ import annotations

import re
from typing import Any

DEVICE_TYPE_LIGHT = 1
DEVICE_TYPE_PLUG = 2

# Lepro appends a four-character opaque identifier to some user-assigned device
# names (for example, ``girls room_U5O5``). It is not part of the name a user
# chose and should not be presented as one in Home Assistant.
_APPENDED_NAME_SUFFIX = re.compile(r"^(?P<name>.+?)_[A-Z0-9]{4}$")


def device_type(device: dict[str, Any]) -> int | None:
    """Return the verified Wi-Fi device type from a discovery payload."""
    for key in ("type", "deviceType", "devType"):
        value = device.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def device_name(device: dict[str, Any], fallback: str = "Lepro Device") -> str:
    """Return the best display name from a discovery payload."""
    for key in ("name", "deviceName", "devName", "nickname", "mac"):
        value = device.get(key)
        if value:
            name = str(value).strip()
            match = _APPENDED_NAME_SUFFIX.match(name)
            return match.group("name") if match else name
    return fallback


def is_light(device: dict[str, Any]) -> bool:
    """Return true when discovery identifies a Wi-Fi light."""
    return device_type(device) == DEVICE_TYPE_LIGHT


def is_plug(device: dict[str, Any]) -> bool:
    """Return true when discovery identifies a Wi-Fi plug."""
    return device_type(device) == DEVICE_TYPE_PLUG


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
