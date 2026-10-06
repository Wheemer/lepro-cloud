"""Switch platform for Lepro Cloud plugs."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import LeproCoordinator
from .const import DOMAIN
from .device import device_name, is_plug
from .protocol import DP_ONLINE, on_payload, state_is_on


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lepro Cloud plug switches."""
    coordinator: LeproCoordinator = entry.runtime_data
    async_add_entities(
        LeproCloudPlugSwitch(coordinator, did, device)
        for did, device in coordinator.devices.items()
        if _is_supported_switch(device)
    )


class LeproCloudPlugSwitch(SwitchEntity):
    """A Lepro cloud-controlled plug switch."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self, coordinator: LeproCoordinator, device_id: str, device: dict[str, Any]
    ) -> None:
        self.coordinator = coordinator
        self.device_id = device_id
        self.device = device
        self._attr_unique_id = f"{DOMAIN}_{device_id}_switch"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device_name(device, "Lepro Plug"),
            "manufacturer": "Lepro",
            "model": device.get("series") or device.get("pid") or "Wi-Fi plug",
        }

    async def async_added_to_hass(self) -> None:
        """Register for MQTT state updates."""
        self.async_on_remove(
            self.coordinator.listen(
                lambda did: self.async_write_ha_state()
                if did == self.device_id
                else None
            )
        )

    @property
    def available(self) -> bool:
        """Return if the plug is available."""
        state = self.coordinator.states.get(self.device_id, {})
        if DP_ONLINE in state:
            try:
                return int(state[DP_ONLINE]) > 0
            except (TypeError, ValueError):
                return False
        return self.coordinator.connected

    @property
    def is_on(self) -> bool | None:
        """Return true if the plug is on."""
        return state_is_on(self.coordinator.states.get(self.device_id, {}))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the plug on."""
        values = on_payload(True)
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )
        self.coordinator.states.setdefault(self.device_id, {}).update(values)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the plug off."""
        values = on_payload(False)
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )
        self.coordinator.states.setdefault(self.device_id, {}).update(values)
        self.async_write_ha_state()


def _is_supported_switch(device: dict[str, Any]) -> bool:
    """Return true when a discovered device is safe to expose as a plug switch."""
    return is_plug(device)
