"""Switch platform for Lepro Cloud plug and TV-strip settings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
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
    entities: list[SwitchEntity] = []
    for did, device in coordinator.devices.items():
        if not _is_supported_switch(device):
            continue
        entities.append(LeproCloudPlugSwitch(coordinator, did, device))
        if _has_lock_switch(device):
            entities.append(LeproCloudPlugLockSwitch(coordinator, did, device))
    for did, device in coordinator.devices.items():
        if _is_stv(device):
            entities.extend(
                (
                    LeproCloudStvSettingSwitch(
                        coordinator, did, device, "d157", "Status LED", "status_led"
                    ),
                    LeproCloudStvSettingSwitch(
                        coordinator,
                        did,
                        device,
                        "d172",
                        "Auto-Toggle Lights",
                        "auto_toggle",
                    ),
                )
            )
    async_add_entities(entities)


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


class LeproCloudPlugLockSwitch(LeproCloudPlugSwitch):
    """The physical-button lock switch exposed by the P1 plug."""

    _attr_name = "Button Lock"

    def __init__(
        self, coordinator: LeproCoordinator, device_id: str, device: dict[str, Any]
    ) -> None:
        super().__init__(coordinator, device_id, device)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_button_lock"

    @property
    def is_on(self) -> bool | None:
        """Return whether the physical-button lock is enabled."""
        state = self.coordinator.states.get(self.device_id, {})
        if "d102" not in state:
            return None
        try:
            return int(state["d102"]) > 0
        except (TypeError, ValueError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the physical-button lock."""
        await self._async_set_lock(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the physical-button lock."""
        await self._async_set_lock(False)

    async def _async_set_lock(self, enabled: bool) -> None:
        values = {"d102": 1 if enabled else 0}
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )
        self.coordinator.states.setdefault(self.device_id, {}).update(values)
        self.async_write_ha_state()


def _has_lock_switch(device: dict[str, Any]) -> bool:
    """Return true only for P1 plugs, whose APK control is d102."""
    series = device.get("series") or device.get("pid")
    return str(series or "").upper() == "P1"


class LeproCloudStvSettingSwitch(SwitchEntity):
    """A verified STV1 TV-strip setting switch."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: LeproCoordinator,
        device_id: str,
        device: dict[str, Any],
        datapoint: str,
        name: str,
        key: str,
    ) -> None:
        self.coordinator = coordinator
        self.device_id = device_id
        self.device = device
        self._datapoint = datapoint
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device_name(device, "Lepro TV Light Strip"),
            "manufacturer": "Lepro",
            "model": device.get("series") or device.get("pid") or "TV light strip",
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
        """Return whether the TV strip is available."""
        state = self.coordinator.states.get(self.device_id, {})
        if DP_ONLINE in state:
            try:
                return int(state[DP_ONLINE]) > 0
            except (TypeError, ValueError):
                return False
        return self.coordinator.connected

    @property
    def is_on(self) -> bool | None:
        """Return the app-reported setting state."""
        value = self.coordinator.states.get(self.device_id, {}).get(self._datapoint)
        if value is None:
            return None
        try:
            return int(value) > 0
        except (TypeError, ValueError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        values = {self._datapoint: 1 if enabled else 0}
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )
        self.coordinator.states.setdefault(self.device_id, {}).update(values)
        self.async_write_ha_state()


def _is_stv(device: dict[str, Any]) -> bool:
    """Return true for the APK's STV1 TV light strip."""
    return str(device.get("series") or device.get("pid") or "").upper() == "STV1"
