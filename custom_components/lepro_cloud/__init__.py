"""Lepro Cloud integration setup."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .client import (
    LeproApiError,
    LeproAuthError,
    LeproCoordinator,
    LeproMqttError,
    cache_authenticated_api,
    take_authenticated_api,
)
from .const import PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lepro Cloud from a config entry."""
    coordinator = LeproCoordinator(
        hass, entry, api=take_authenticated_api(hass, entry.unique_id)
    )
    try:
        await coordinator.async_start()
    except LeproAuthError as err:
        await coordinator.async_stop()
        raise ConfigEntryAuthFailed(str(err)) from err
    except (LeproApiError, LeproMqttError) as err:
        await coordinator.async_stop()
        raise ConfigEntryNotReady(str(err)) from err
    except BaseException:
        await coordinator.async_stop()
        raise

    async def async_stop_on_hass_shutdown(_event: Event) -> None:
        """Clean up certificate files before Home Assistant closes its loop."""
        await coordinator.async_stop()

    entry.runtime_data = coordinator
    try:
        if getattr(coordinator, "devices", None) is not None:
            _reconcile_registry(hass, entry, coordinator)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        # MQTT has already started at this point. Do not leave the transport
        # running if a platform cannot be created and Home Assistant retries.
        try:
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        finally:
            await coordinator.async_stop()
        raise
    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, async_stop_on_hass_shutdown
        )
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Lepro Cloud platforms and its MQTT transport."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
        coordinator = entry.runtime_data
        if (
            getattr(coordinator.api, "token", None)
            and not coordinator._reauth_requested
        ):
            cache_authenticated_api(
                hass, entry.unique_id, coordinator.api, replace=False
            )
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Discard credentials cached for a reload when the account is removed."""
    take_authenticated_api(hass, entry.unique_id)


def _reconcile_registry(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: LeproCoordinator
) -> None:
    """Remove only this entry's departed devices, preserving user overrides."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from .const import DOMAIN
    from .device import device_info

    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    valid = {(DOMAIN, did) for did in coordinator.devices}
    for registered in dr.async_entries_for_config_entry(devices, entry.entry_id):
        identifiers = registered.identifiers & valid
        if not identifiers:
            for entity in er.async_entries_for_device(entities, registered.id):
                if entity.config_entry_id == entry.entry_id:
                    entities.async_remove(entity.entity_id)
            if hasattr(registered, "config_entry_id"):
                if registered.config_entry_id == entry.entry_id:
                    devices.async_remove_device(registered.id)
            elif registered.config_entries == {entry.entry_id}:
                devices.async_remove_device(registered.id)
            else:
                devices.async_update_device(
                    registered.id, remove_config_entry_id=entry.entry_id
                )
            continue
        _, did = next(iter(identifiers))
        info = device_info(coordinator.devices[did], did)
        devices.async_update_device(
            registered.id,
            **{
                key: info[key]
                for key in ("name", "model", "sw_version", "hw_version")
                if key in info
            },
        )
