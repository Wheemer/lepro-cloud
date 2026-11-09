"""Redacted integration diagnostics without account or device identifiers."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .capabilities import resolved_picker
from .catalog import PRODUCT_CONFIGS
from .const import DOMAIN, REGIONS
from .device import device_type, product_series
from .log_helpers import (
    safe_code,
    safe_picker,
    safe_region,
    safe_series,
    safe_version,
    state_fields,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return only explicitly allowed capability and transport information."""
    coordinator = entry.runtime_data
    override = entry.data.get("region_override")
    if not isinstance(override, str) or override not in REGIONS:
        override = None
    return {
        "region": safe_region(entry.data.get("region")),
        "region_selection": (
            "vendor_app"
            if entry.data.get("auth_implementation") == DOMAIN
            else "override"
            if override is not None
            else "automatic"
        ),
        "region_override": override,
        "active_region": safe_region(
            getattr(getattr(coordinator, "api", None), "region", None)
        ),
        "mqtt_connected": coordinator.connected,
        "mqtt_messages_received": getattr(coordinator, "_property_messages", 0),
        "state_reports_accepted": getattr(coordinator, "_accepted_reports", 0),
        "state_reports_rejected": getattr(coordinator, "_rejected_state_reports", 0),
        "state_fields_filtered": getattr(coordinator, "_filtered_state_fields", 0),
        "state_query_retry_rounds": getattr(coordinator, "_state_query_retries", 0),
        "devices": [
            {
                "device": index,
                "series": safe_series(product_series(device)),
                "reported_series": safe_series(device.get("series")),
                "type": device_type(device)
                if device_type(device) in (0, 1, 2, 3)
                else None,
                "reported_type": safe_code(device.get("type"))
                if safe_code(device.get("type")) in (0, 1, 2, 3)
                else None,
                "picker": safe_picker(resolved_picker(device, PRODUCT_CONFIGS)),
                "family_context_count": len(device["_family_ids"])
                if isinstance(device.get("_family_ids"), list)
                else 0,
                "firmware": safe_version(device.get("fwVersion")),
                "cloud_control": (
                    safe_code(device.get("control"))
                    if safe_code(device.get("control")) in range(-1, 8)
                    else None
                ),
                "datapoints": state_fields(coordinator.states.get(did, {})),
                "scene_count": len(device["scenes"])
                if isinstance(device.get("scenes"), list)
                else 0,
                "fresh": did in coordinator._fresh,
            }
            for index, (did, device) in enumerate(coordinator.devices.items(), 1)
        ],
    }
