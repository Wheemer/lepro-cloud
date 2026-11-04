"""Config flow for Lepro Cloud."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import config_entry_oauth2_flow as oauth2

from .client import (
    LeproApi,
    LeproApiError,
    LeproAuthError,
    LeproError,
    LeproResponseError,
    cache_authenticated_api,
)
from .const import CONF_REGION, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _account_unique_id(region: str, username: str) -> str:
    """Return the stable unique ID for a Lepro Cloud account."""
    return f"{region}:{username.lower()}"


def _app_account_configured(hass: Any, api: LeproApi) -> bool:
    """Prevent an app-authorized account being added again using a password."""
    uid = getattr(api, "uid", None)
    return bool(
        uid
        and hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, f"app:{uid}")
    )


def _credentials_schema(*, username: str | None = None) -> vol.Schema:
    """Return the Lepro Cloud credentials form schema."""
    username_field = (
        vol.Required(CONF_USERNAME, default=username)
        if username is not None
        else vol.Required(CONF_USERNAME)
    )
    fields: dict[Any, Any] = {
        username_field: str,
        vol.Required(CONF_PASSWORD): str,
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


def _log_api_error(error: LeproApiError) -> None:
    """Log a safe config-flow diagnostic for a Lepro API error."""
    _LOGGER.warning(
        "Lepro Cloud config flow API error (%s): %s",
        type(error).__name__,
        str(error) or "no message",
    )


class LeproCloudFlow(oauth2.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Handle a Lepro Cloud config flow."""

    VERSION = 1
    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Choose email/password or authorization through the Lepro app."""
        if user_input is not None:
            return await self.async_step_email(user_input)
        return self.async_show_menu(step_id="user", menu_options=["email", "app"])

    async def async_step_app(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Start the vendor-owned app authorization handoff."""
        if user_input is None:
            return self.async_show_form(step_id="app", data_schema=vol.Schema({}))
        from .app_auth import LeproAppOAuthImplementation

        self.flow_impl = LeproAppOAuthImplementation(self.hass)
        self.async_register_implementation(self.hass, self.flow_impl)
        return await self.async_step_auth()

    async def async_step_creation(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Map vendor session errors without leaking callback credentials."""
        try:
            return await super().async_step_creation(user_input)
        except LeproAuthError:
            return self.async_abort(reason="invalid_auth")
        except LeproApiError:
            return self.async_abort(reason="cannot_connect")

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> dict[str, Any]:
        """Store app credentials and bind reauthentication to the same UID."""
        token = data["token"]
        uid = str(token["uid"])
        unique_id = f"app:{uid}"
        source = self.context.get("source")
        entry = None
        if source in {"reauth", "reconfigure"}:
            entry = (
                self._get_reauth_entry()
                if source == "reauth"
                else self._get_reconfigure_entry()
            )
            if str(entry.data.get("token", {}).get("uid") or "") != uid:
                return self.async_abort(reason="wrong_account")
        duplicate = await self.async_set_unique_id(unique_id)
        if duplicate is not None and (
            entry is None or duplicate.entry_id != entry.entry_id
        ):
            return self.async_abort(reason="already_configured")
        account = token.get("account", "")
        # Older email entries use the email/region ID, not the vendor UID.
        if account:
            legacy = self.hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, _account_unique_id(token["region"], account)
            )
            if legacy is not None and (
                entry is None or legacy.entry_id != entry.entry_id
            ):
                return self.async_abort(reason="already_configured")
        title = f"Lepro Cloud ({account})" if account else "Lepro Cloud"
        stored = {**data, CONF_REGION: token["region"]}
        if entry is not None:
            return self.async_update_reload_and_abort(
                entry,
                unique_id=unique_id,
                title=title,
                data=stored,
                reason="reauth_successful"
                if source == "reauth"
                else "reconfigure_successful",
            )
        return self.async_create_entry(title=title, data=stored)

    async def async_step_email(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()

            try:
                region = await _async_account_region(self.hass, username)
                api = LeproApi(self.hass, region)
                await api.async_login(username, password)
            except (LeproApiError, LeproAuthError) as err:
                _log_api_error(err)
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
                    },
                )

        return self.async_show_form(
            step_id="email",
            data_schema=_credentials_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle reconfiguration from the config-entry Configure action."""
        entry = self._get_reconfigure_entry()
        if entry.data.get("auth_implementation") == DOMAIN:
            return await self.async_step_app(user_input)
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()
            try:
                region = await _async_account_region(self.hass, username)
                api = LeproApi(self.hass, region)
                await api.async_login(username, password)
            except (LeproApiError, LeproAuthError) as err:
                _log_api_error(err)
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
                        reason="reconfigure_successful",
                        data={
                            **entry.data,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_REGION: region,
                        },
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(username=entry.data[CONF_USERNAME]),
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
            return await self.async_step_app(user_input)
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()
            if username.casefold() != entry.data[CONF_USERNAME].strip().casefold():
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=_credentials_schema(username=entry.data[CONF_USERNAME]),
                    errors={"base": "wrong_account"},
                )
            try:
                region = await _async_account_region(self.hass, username)
                api = LeproApi(self.hass, region)
                await api.async_login(username, password)
            except (LeproApiError, LeproAuthError) as err:
                _log_api_error(err)
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
                            **entry.data,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_REGION: region,
                        },
                        reason="reauth_successful",
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_credentials_schema(username=entry.data[CONF_USERNAME]),
            errors=errors,
        )
