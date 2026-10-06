"""Lepro Cloud integration setup."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .client import LeproApiError, LeproAuthError, LeproCoordinator, LeproMqttError
from .const import PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lepro Cloud from a config entry."""
    coordinator = LeproCoordinator(hass, entry)
    try:
        await coordinator.async_start()
    except LeproAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except (LeproApiError, LeproMqttError) as err:
        raise ConfigEntryNotReady(str(err)) from err

    async def async_stop_on_hass_shutdown(_event: Event) -> None:
        """Clean up certificate files before Home Assistant closes its loop."""
        await coordinator.async_stop()

    entry.runtime_data = coordinator
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop_on_hass_shutdown)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Lepro Cloud platforms and its MQTT transport."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
