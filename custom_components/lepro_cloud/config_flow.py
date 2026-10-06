"""Config flow for Lepro Cloud."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .client import (
    LeproApi,
    LeproApiError,
    LeproAuthError,
    LeproError,
    LeproResponseError,
)
from .const import CONF_REGION, DOMAIN, REGIONS

_LOGGER = logging.getLogger(__name__)


def _flow_error(error: LeproError) -> str:
    """Return the config-flow error key for a Lepro exception."""
    if isinstance(error, LeproAuthError):
        return "invalid_auth"
    if isinstance(error, LeproResponseError):
        return "invalid_response"
    return "cannot_connect"


def _log_api_error(error: LeproApiError) -> None:
    """Log a safe config-flow diagnostic for a Lepro API error."""
    _LOGGER.warning(
        "Lepro Cloud config flow API error (%s): %s",
        type(error).__name__,
        str(error) or "no message",
    )


class LeproCloudFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Lepro Cloud config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            # Match the Android app, which trims both fields before login.
            password = user_input[CONF_PASSWORD].strip()
            region = user_input[CONF_REGION]
            await self.async_set_unique_id(f"{region}:{username.lower()}")
            self._abort_if_unique_id_configured()

            try:
                await LeproApi(self.hass, region).async_login(
                    username, password
                )
            except LeproApiError as err:
                _log_api_error(err)
                errors["base"] = _flow_error(err)
            else:
                return self.async_create_entry(
                    title=f"Lepro Cloud ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_REGION: region,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_REGION, default="north_america"): vol.In(REGIONS),
                }
            ),
            errors=errors,
        )
