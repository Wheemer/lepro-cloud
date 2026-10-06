"""Device classification helpers for Lepro Cloud discovery."""

from __future__ import annotations

from typing import Any

DEVICE_TYPE_LIGHT = 1
DEVICE_TYPE_PLUG = 2


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
            return str(value)
    return fallback


def is_light(device: dict[str, Any]) -> bool:
    """Return true when discovery identifies a Wi-Fi light."""
    return device_type(device) == DEVICE_TYPE_LIGHT


def is_plug(device: dict[str, Any]) -> bool:
    """Return true when discovery identifies a Wi-Fi plug."""
    return device_type(device) == DEVICE_TYPE_PLUG
