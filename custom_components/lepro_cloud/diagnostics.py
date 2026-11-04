"""Redacted integration diagnostics without account or device identifiers."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return only explicitly allowed capability and transport information."""
    coordinator = entry.runtime_data
    return {
        "region": entry.data.get("region"),
        "mqtt_connected": coordinator.connected,
        "devices": [
            {
                "series": str(device.get("series", "unknown")),
                "firmware": str(device.get("fwVersion", "unknown")),
                "cloud_control": device.get("control"),
                "datapoints": sorted(
                    key
                    for key in coordinator.states.get(did, {})
                    if key == "online" or key.startswith("d") and key[1:].isdigit()
                ),
                "scene_count": len(device.get("scenes", [])),
                "fresh": did in coordinator._fresh,
            }
            for did, device in coordinator.devices.items()
        ],
    }
