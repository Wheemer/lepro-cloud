"""Lepro Cloud integration setup."""

import logging

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
from .const import DOMAIN, PLATFORMS
from .log_helpers import error_summary, log_failure

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lepro Cloud from a config entry."""
    api = take_authenticated_api(hass, entry.unique_id)
    if entry.data.get("auth_implementation") == DOMAIN:
        from .app_auth import LeproAppApi

        if not isinstance(api, LeproAppApi):
            api = LeproAppApi(hass, entry)
    coordinator = LeproCoordinator(hass, entry, api=api)
    try:
        await coordinator.async_start()
    except LeproAuthError as err:
        log_failure(
            _LOGGER, logging.WARNING, "Lepro setup requires reauthentication", err
        )
        await coordinator.async_stop()
        raise ConfigEntryAuthFailed(error_summary(err)) from None
    except (LeproApiError, LeproMqttError) as err:
        log_failure(_LOGGER, logging.DEBUG, "Lepro setup deferred", err)
        await coordinator.async_stop()
        raise ConfigEntryNotReady(error_summary(err)) from None
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
        if getattr(coordinator, "devices", None):
            _remove_obsolete_primary_entities(hass, entry, coordinator)
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
    _LOGGER.debug(
        "Lepro setup completed: devices=%s", len(getattr(coordinator, "devices", {}))
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
    _LOGGER.debug(
        "Lepro unload completed: platforms_unloaded=%s transport_stopped=%s",
        unloaded,
        unloaded,
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
    from .device import device_info, preserve_device_name
    from .scenes import effect_family

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
        device = coordinator.devices[did]
        preserve_device_name(device, registered.name)
        # A picker selects an app UI, not a complete inventory of native controls.
        # Keep an existing ordinary bulb's CT control until fresh reports arrive.
        if (
            device.get("_color_picker") == "rgb"
            and effect_family(device, coordinator.effect_types) == "smartbulb"
        ):
            for entity in er.async_entries_for_device(entities, registered.id):
                if (
                    entity.config_entry_id == entry.entry_id
                    and entity.domain == "light"
                ):
                    capabilities = entity.capabilities or {}
                    if "color_temp" in capabilities.get("supported_color_modes", []):
                        device["_native_color_temp"] = True
        info = device_info(device, did)
        devices.async_update_device(
            registered.id,
            **{
                key: info[key]
                for key in ("name", "model", "sw_version", "hw_version")
                if key in info
            },
        )


def _remove_obsolete_primary_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: LeproCoordinator
) -> None:
    """Retire the previous domain only after its replacement is registered."""
    from homeassistant.helpers import entity_registry as er

    from .device import is_light, is_plug

    entities = er.async_get(hass)
    for did, device in coordinator.devices.items():
        if is_light(device):
            current_domain, current_uid = "light", f"{DOMAIN}_{did}"
            old_domain, old_uid = "switch", f"{DOMAIN}_{did}_switch"
        elif is_plug(device):
            current_domain, current_uid = "switch", f"{DOMAIN}_{did}_switch"
            old_domain, old_uid = "light", f"{DOMAIN}_{did}"
        else:
            continue
        current_id = entities.async_get_entity_id(current_domain, DOMAIN, current_uid)
        current = entities.async_get(current_id) if current_id else None
        if current is None or current.config_entry_id != entry.entry_id:
            continue
        old_id = entities.async_get_entity_id(old_domain, DOMAIN, old_uid)
        old = entities.async_get(old_id) if old_id else None
        if old is not None and old.config_entry_id == entry.entry_id:
            # Exact generated primary identity only: never remove settings,
            # diagnostics, or another integration/account's registry entry.
            entities.async_remove(old.entity_id)
