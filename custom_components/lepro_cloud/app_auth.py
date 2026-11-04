"""Lepro app authorization handoff and renewable vendor sessions."""

from __future__ import annotations

import base64
import binascii
import math
import time
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from homeassistant.helpers import config_entry_oauth2_flow as oauth2

from .client import LeproApi, LeproAuthError, LeproResponseError
from .const import DOMAIN, REGION_DISCOVERY_HOST, REGIONS

# C9860k.m18241d and the backend's authenticated /oauth2/app handler.
APP_CLIENT_ID = "jtn2pfwl95"
APP_AUTHORIZE_URL = f"https://{REGION_DISCOVERY_HOST}/oauth2/app/"
# AESCipher.java: the app wraps both community and authorization tokens with
# AES-CBC/PKCS7, then Base64. This constant is protocol data, not a user secret.
_APP_TOKEN_KEY = b"8devA4f0fa73jd9q"
# Maintenance runs every five minutes; leave room for retries before expiry.
_RENEWAL_MARGIN_SECONDS = 3600


def _wrap_app_token(value: str) -> str:
    """Encode the app's thirdToken exactly as AESCipher.encrypt does."""
    if not isinstance(value, str) or not 16 <= len(value) <= 4096:
        raise LeproAuthError("Invalid Lepro app authorization")
    try:
        base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise LeproAuthError("Invalid Lepro app authorization") from None
    padder = PKCS7(128).padder()
    padded = padder.update(value.encode()) + padder.finalize()
    encryptor = Cipher(
        algorithms.AES(_APP_TOKEN_KEY), modes.CBC(_APP_TOKEN_KEY)
    ).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


async def async_exchange_app_token(
    hass: Any, app_token: str, *, expected_uid: str | None = None
) -> dict[str, Any]:
    """Exchange a vendor callback/renewal token and obtain its successor.

    Both paths were verified against the real API. This is Lepro's app web-token
    protocol, not the partner /oauth2/token endpoint that needs a client secret.
    """
    wrapped = _wrap_app_token(app_token)
    api = LeproApi(hass, host=REGION_DISCOVERY_HOST)
    body = {
        "platform": "2",
        "thirdToken": wrapped,
        "timestamp": str(int(time.time())),
    }
    try:
        region_data = await api._request(
            "POST", "/web/token/region", body, json_body=True
        )
    except LeproResponseError as err:
        if err.code == -101:
            raise LeproAuthError("Lepro app authorization was rejected") from None
        raise
    host = region_data.get("apiHost")
    region = next((key for key, value in REGIONS.items() if value == host), None)
    if region is None:
        raise LeproResponseError("Lepro returned an unknown account region")
    api._host = host
    body["timestamp"] = str(int(time.time()))
    try:
        login = await api._request("POST", "/web/token/refresh", body, json_body=True)
    except LeproResponseError as err:
        if err.code == -101:
            raise LeproAuthError("Lepro app authorization was rejected") from None
        raise
    uid = str(login.get("uid") or "")
    access_token, secret = login.get("token"), login.get("secret")
    if not uid or not isinstance(access_token, str) or not access_token:
        raise LeproAuthError("Lepro returned incomplete app credentials")
    if not isinstance(secret, str) or not secret:
        raise LeproAuthError("Lepro returned incomplete app credentials")
    if expected_uid is not None and uid != str(expected_uid):
        raise LeproAuthError("Lepro app authorization belongs to another account")
    api.token, api.uid, api.secret = access_token, uid, secret
    profile = await api.async_profile()
    if str(profile.get("uid") or "") != uid:
        raise LeproAuthError("Lepro returned inconsistent account identity")
    account = profile.get("username")
    if not isinstance(account, str):
        account = ""
    successor = await api._request("POST", "/inapp/token")
    refresh_token = successor.get("userToken")
    _wrap_app_token(refresh_token)  # Validate before persisting any credentials.
    try:
        api_expire = int(login["expire"])
        refresh_expire = int(successor["tokenExpire"])
    except (KeyError, TypeError, ValueError, OverflowError):
        raise LeproResponseError("Lepro returned invalid credential expiry") from None
    expires_in = (
        min(api_expire, refresh_expire) - int(time.time()) - _RENEWAL_MARGIN_SECONDS
    )
    if expires_in <= 60:
        raise LeproResponseError("Lepro returned expired app credentials")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "uid": uid,
        "account": account,
        "secret": secret,
        "region": region,
        "api_expires_at": api_expire,
        "refresh_expires_at": refresh_expire,
        "expires_in": expires_in,
        "token_type": "Bearer",
    }


class LeproAppOAuthImplementation(oauth2.LocalOAuth2Implementation):
    """Use HA's signed callback state with Lepro's app-owned authorization."""

    def __init__(self, hass: Any) -> None:
        super().__init__(hass, DOMAIN, APP_CLIENT_ID, "", APP_AUTHORIZE_URL, "")

    @property
    def name(self) -> str:
        return "Lepro app"

    @property
    def extra_authorize_data(self) -> dict[str, str]:
        return {"scope": "user"}

    async def async_resolve_external_data(self, external_data: Any) -> dict:
        code = external_data.get("code")
        if not isinstance(code, str):
            raise LeproAuthError("Missing Lepro app authorization")
        # Lepro's returned URL contains raw '+' characters in its Base64 code.
        # HA's normal URL parser turns them into spaces. Restore only this code,
        # after HA has validated the signed state; never alter the state itself.
        return await async_exchange_app_token(self.hass, code.replace(" ", "+"))

    async def _async_refresh_token(self, token: dict) -> dict:
        uid = token.get("uid")
        if not uid:
            raise LeproAuthError("Missing Lepro app account identity")
        return await async_exchange_app_token(
            self.hass, token.get("refresh_token"), expected_uid=str(uid)
        )


class LeproAppApi(LeproApi):
    """Keep API credentials synchronized with HA's persisted OAuth2 session."""

    def __init__(self, hass: Any, entry: Any) -> None:
        super().__init__(hass, host=REGION_DISCOVERY_HOST)
        self._entry = entry
        self._oauth = oauth2.OAuth2Session(
            hass, entry, LeproAppOAuthImplementation(hass)
        )

    async def async_restore_session(self) -> None:
        """Restore or renew persisted credentials without a password login."""
        token = self._entry.data.get("token")
        if not isinstance(token, dict):
            raise LeproAuthError("Missing Lepro app session")
        expiry = token.get("expires_at")
        if (
            not isinstance(expiry, (int, float))
            or not math.isfinite(expiry)
            or not token.get("uid")
        ):
            raise LeproAuthError("Invalid Lepro app session")
        await self._oauth.async_ensure_token_valid()
        token = self._oauth.token
        region = token.get("region")
        if (
            region not in REGIONS
            or not token.get("access_token")
            or not token.get("secret")
            or not token.get("uid")
        ):
            raise LeproAuthError("Incomplete Lepro app session")
        # Do not undo a validated -100 API-host migration on the next request.
        # A newly restored/renewed token supplies its freshly resolved region.
        if self.token != token["access_token"] or self._host == REGION_DISCOVERY_HOST:
            self._host = REGIONS[region]
        self.token = token["access_token"]
        self.secret = token["secret"]
        self.uid = str(token["uid"])

    async def _request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        await self.async_restore_session()
        return await super()._request(*args, **kwargs)
