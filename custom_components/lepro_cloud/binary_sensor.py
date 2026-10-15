"""Diagnostic binary sensors for Lepro Cloud devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import LeproCoordinator
from .const import DOMAIN
from .device import device_info, is_supported_device
from .protocol import DP_ONLINE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lepro Cloud diagnostic binary sensors."""
    coordinator: LeproCoordinator = entry.runtime_data
    async_add_entities(
        LeproCloudConnectionSensor(coordinator, did, device)
        for did, device in coordinator.devices.items()
        if is_supported_device(device)
    )


class LeproCloudConnectionSensor(BinarySensorEntity):
    """Expose the app-reported cloud connection for a Lepro device."""

    _attr_has_entity_name = True
    _attr_name = "Cloud connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: LeproCoordinator, device_id: str, device: dict[str, Any]
    ) -> None:
        self.coordinator = coordinator
        self.device_id = device_id
        self.device = device
        self._attr_unique_id = f"{DOMAIN}_{device_id}_cloud_connection"
        self._attr_device_info = device_info(device, device_id)

    async def async_added_to_hass(self) -> None:
        """Register for MQTT state updates."""
        self.async_on_remove(
            self.coordinator.listen(
                lambda did: (
                    self.async_write_ha_state() if did == self.device_id else None
                )
            )
        )

    @property
    def available(self) -> bool:
        """Return whether Home Assistant is connected to the Lepro MQTT broker."""
        return self.coordinator.connected

    @property
    def is_on(self) -> bool | None:
        """Return the device's app-reported cloud connection state."""
        value = self.coordinator.states.get(self.device_id, {}).get(DP_ONLINE)
        if value is None:
            return None
        try:
            return int(value) > 0
        except (TypeError, ValueError):
            return None
