"""Light platform for Lepro Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import LeproCoordinator
from .const import DOMAIN
from .device import device_name, is_light
from .protocol import (
    DP_BRIGHTNESS,
    DP_ONLINE,
    brightness_payload,
    lepro_to_ha_brightness,
    on_payload,
    state_is_on,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lepro Cloud lights."""
    coordinator: LeproCoordinator = entry.runtime_data
    async_add_entities(
        LeproCloudLight(coordinator, did, device)
        for did, device in coordinator.devices.items()
        if _is_supported_light(device)
    )


class LeproCloudLight(LightEntity):
    """A Lepro cloud-controlled light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self, coordinator: LeproCoordinator, device_id: str, device: dict[str, Any]
    ) -> None:
        self.coordinator = coordinator
        self.device_id = device_id
        self.device = device
        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device_name(device, "Lepro Light"),
            "manufacturer": "Lepro",
            "model": device.get("series") or device.get("pid") or "Wi-Fi light",
        }

    async def async_added_to_hass(self) -> None:
        """Register for MQTT state updates."""
        self.async_on_remove(
            self.coordinator.listen(
                lambda did: self.async_write_ha_state() if did == self.device_id else None
            )
        )

    @property
    def available(self) -> bool:
        """Return if the light is available."""
        state = self.coordinator.states.get(self.device_id, {})
        if DP_ONLINE in state:
            try:
                return int(state[DP_ONLINE]) > 0
            except (TypeError, ValueError):
                return False
        return self.coordinator.connected

    @property
    def is_on(self) -> bool | None:
        """Return true if the light is on."""
        return state_is_on(self.coordinator.states.get(self.device_id, {}))

    @property
    def brightness(self) -> int | None:
        """Return brightness in Home Assistant scale."""
        return lepro_to_ha_brightness(
            self.coordinator.states.get(self.device_id, {}).get(DP_BRIGHTNESS)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        values: dict[str, Any] = on_payload(True)
        if ATTR_BRIGHTNESS in kwargs:
            values.update(brightness_payload(kwargs[ATTR_BRIGHTNESS]))
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )
        self.coordinator.states.setdefault(self.device_id, {}).update(values)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        values = on_payload(False)
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )
        self.coordinator.states.setdefault(self.device_id, {}).update(values)
        self.async_write_ha_state()


def _is_supported_light(device: dict[str, Any]) -> bool:
    """Return true when a discovered device is safe to expose as a basic light."""
    return is_light(device)
