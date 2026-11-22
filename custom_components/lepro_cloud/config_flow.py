"""Config flow for Lepro Cloud."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector

from .client import (
    LeproApi,
    LeproApiError,
    LeproAuthError,
    LeproError,
    LeproResponseError,
    cache_authenticated_api,
)
from .const import CONF_REGION, CONF_REGION_OVERRIDE, DOMAIN, REGIONS
from .log_helpers import error_details, safe_region

_LOGGER = logging.getLogger(__name__)


def _account_unique_id(region: str, username: str) -> str:
    """Return the stable unique ID for a Lepro Cloud account."""
    return f"{region}:{username.lower()}"


def _app_account_configured(hass: Any, api: LeproApi, entry: Any = None) -> bool:
    """Prevent an app-authorized account being added again using a password."""
    uid = getattr(api, "uid", None)
    existing = (
        hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, f"app:{uid}")
        if uid
        else None
    )
    return existing is not None and existing is not entry


def _credentials_schema(
    *, username: str | None = None, region_override: str = "auto"
) -> vol.Schema:
    """Return the Lepro Cloud credentials form schema."""
    username_field = (
        vol.Required(CONF_USERNAME, default=username)
        if username is not None
        else vol.Required(CONF_USERNAME)
    )
    fields: dict[Any, Any] = {
        username_field: str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(
            CONF_REGION_OVERRIDE, default=region_override
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value=value, label=label)
                    for value, label in (
                        ("auto", "Automatic"),
                        ("north_america", "North America"),
                        ("europe", "Europe"),
                        ("far_east", "Far East"),
                    )
                ]
            )
        ),
    }
    return vol.Schema(fields)


async def _async_account_region(hass: Any, username: str) -> str:
    """Ask Lepro's bootstrap service for the account's API region."""
    return await LeproApi.async_resolve_region(hass, username)


def _flow_error(error: LeproError) -> str:
    """Return the config-flow error key for a Lepro exception."""
    if isinstance(error, LeproAuthError):
        return "invalid_auth"
    if isinstance(error, LeproResponseError):
        return "invalid_response"
    return "cannot_connect"


def _log_api_error(
    error: LeproError,
    *,
    stage: str = "unknown",
    region: str | None = None,
    flow_step: str = "unknown",
) -> None:
    """Log only structured metadata and locally defined error descriptions."""
    _LOGGER.warning(
        "Lepro Cloud config flow API error: step=%s stage=%s %s",
        flow_step,
        stage,
        error_details(error, region=region),
    )


async def _resolve_login_region(hass: Any, username: str, override: str) -> str:
    """Bypass bootstrap only for an explicitly selected allowlisted region."""
    if override == "auto":
        selected = await _async_account_region(hass, username)
        _LOGGER.debug(
            "Lepro server selection: mode=automatic region=%s", safe_region(selected)
        )
        return selected
    if override not in REGIONS:
        raise LeproResponseError("Unsupported regional server selection")
    _LOGGER.debug(
        "Lepro server selection: mode=override region=%s", safe_region(override)
    )
    return override


def _override_data(override: str) -> dict[str, str]:
    return {CONF_REGION_OVERRIDE: override} if override != "auto" else {}


class LeproCloudFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Lepro Cloud config flow."""

    VERSION = 1
    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Open the supported email and password form."""
        return await self.async_step_email(user_input)

    async def async_step_email(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()

            override = user_input.get(CONF_REGION_OVERRIDE, "auto")
            region = None
            stage = "region_lookup" if override == "auto" else "server_override"
            try:
                region = await _resolve_login_region(self.hass, username, override)
                stage = "login"
                api = LeproApi(self.hass, region)
                await api.async_login(username, password)
                actual_region = getattr(api, "region", None)
                if actual_region in REGIONS:
                    region = actual_region
            except (LeproApiError, LeproAuthError) as err:
                _log_api_error(err, stage=stage, region=region, flow_step="email")
                errors["base"] = _flow_error(err)
            else:
                if _app_account_configured(self.hass, api):
                    return self.async_abort(reason="already_configured")
                await self.async_set_unique_id(_account_unique_id(region, username))
                self._abort_if_unique_id_configured()
                cache_authenticated_api(
                    self.hass, _account_unique_id(region, username), api
                )
                return self.async_create_entry(
                    title=f"Lepro Cloud ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_REGION: region,
                        **_override_data(override),
                    },
                )

        return self.async_show_form(
            step_id="email",
            data_schema=_credentials_schema(
                region_override=user_input.get(CONF_REGION_OVERRIDE, "auto")
                if user_input
                else "auto"
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle reconfiguration from the config-entry Configure action."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()
            override = user_input.get(
                CONF_REGION_OVERRIDE, entry.data.get(CONF_REGION_OVERRIDE, "auto")
            )
            region = None
            stage = "region_lookup" if override == "auto" else "server_override"
            try:
                region = await _resolve_login_region(self.hass, username, override)
                stage = "login"
                api = LeproApi(self.hass, region)
                await api.async_login(username, password)
                actual_region = getattr(api, "region", None)
                if actual_region in REGIONS:
                    region = actual_region
            except (LeproApiError, LeproAuthError) as err:
                _log_api_error(err, stage=stage, region=region, flow_step="reconfigure")
                errors["base"] = _flow_error(err)
            else:
                if _app_account_configured(self.hass, api, entry):
                    return self.async_abort(reason="already_configured")
                unique_id = _account_unique_id(region, username)
                duplicate_entry = await self.async_set_unique_id(unique_id)
                if (
                    duplicate_entry is not None
                    and duplicate_entry.entry_id != entry.entry_id
                ):
                    errors["base"] = "already_configured"
                else:
                    cache_authenticated_api(self.hass, unique_id, api)
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=unique_id,
                        title=f"Lepro Cloud ({username})",
                        reason="reconfigure_successful",
                        data={
                            **{
                                key: value
                                for key, value in entry.data.items()
                                if key
                                not in {
                                    CONF_REGION_OVERRIDE,
                                    "auth_implementation",
                                    "token",
                                }
                            },
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_REGION: region,
                            **_override_data(override),
                        },
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(
                username=entry.data.get(CONF_USERNAME),
                region_override=(
                    user_input.get(
                        CONF_REGION_OVERRIDE,
                        entry.data.get(CONF_REGION_OVERRIDE, "auto"),
                    )
                    if user_input
                    else entry.data.get(CONF_REGION_OVERRIDE, "auto")
                ),
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> dict[str, Any]:
        """Handle a request to reauthenticate an existing entry."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Confirm updated credentials and reload the existing entry."""
        entry = self._get_reauth_entry()
        if entry.data.get("auth_implementation") == DOMAIN:
            return self.async_abort(reason="legacy_app_reauth")
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()
            if username.casefold() != entry.data[CONF_USERNAME].strip().casefold():
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=_credentials_schema(
                        username=entry.data.get(CONF_USERNAME),
                        region_override=(
                            user_input.get(
                                CONF_REGION_OVERRIDE,
                                entry.data.get(CONF_REGION_OVERRIDE, "auto"),
                            )
                            if user_input
                            else entry.data.get(CONF_REGION_OVERRIDE, "auto")
                        ),
                    ),
                    errors={"base": "wrong_account"},
                )
            override = user_input.get(
                CONF_REGION_OVERRIDE, entry.data.get(CONF_REGION_OVERRIDE, "auto")
            )
            region = None
            stage = "region_lookup" if override == "auto" else "server_override"
            try:
                region = await _resolve_login_region(self.hass, username, override)
                stage = "login"
                api = LeproApi(self.hass, region)
                await api.async_login(username, password)
                actual_region = getattr(api, "region", None)
                if actual_region in REGIONS:
                    region = actual_region
            except (LeproApiError, LeproAuthError) as err:
                _log_api_error(
                    err, stage=stage, region=region, flow_step="reauth_confirm"
                )
                errors["base"] = _flow_error(err)
            else:
                if _app_account_configured(self.hass, api):
                    return self.async_abort(reason="already_configured")
                unique_id = _account_unique_id(region, username)
                duplicate_entry = await self.async_set_unique_id(unique_id)
                if (
                    duplicate_entry is not None
                    and duplicate_entry.entry_id != entry.entry_id
                ):
                    errors["base"] = "already_configured"
                else:
                    cache_authenticated_api(self.hass, unique_id, api)
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=unique_id,
                        title=f"Lepro Cloud ({username})",
                        data={
                            **{
                                key: value
                                for key, value in entry.data.items()
                                if key != CONF_REGION_OVERRIDE
                            },
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_REGION: region,
                            **_override_data(override),
                        },
                        reason="reauth_successful",
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_credentials_schema(
                username=entry.data.get(CONF_USERNAME),
                region_override=(
                    user_input.get(
                        CONF_REGION_OVERRIDE,
                        entry.data.get(CONF_REGION_OVERRIDE, "auto"),
                    )
                    if user_input
                    else entry.data.get(CONF_REGION_OVERRIDE, "auto")
                ),
            ),
            errors=errors,
        )
