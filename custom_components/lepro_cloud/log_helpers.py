"""Allowlisted support diagnostics; never stringify network errors or payloads."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .catalog import APK_ERROR_CODES, PRODUCT_CONFIGS
from .const import REGIONS
from .device import device_type, product_series
from .protocol import parse_wire_integer

SAFE_STATE_FIELDS = frozenset(
    {
        "online",
        "d1",
        "d2",
        "d3",
        "d4",
        "d5",
        "d6",
        "d50",
        "d52",
        "d53",
        "d100",
        "d101",
        "d102",
        "d157",
        "d172",
    }
)
_SERIES = frozenset(item["series"].upper() for item in PRODUCT_CONFIGS)
_PICKERS = frozenset(item["colorPicker"] for item in PRODUCT_CONFIGS)
_ERROR_TYPES = frozenset(
    {
        "LeproError",
        "LeproApiError",
        "LeproAuthError",
        "LeproMqttError",
        "LeproResponseError",
        "MqttKeyError",
        "TimeoutError",
        "OSError",
        "ValueError",
        "TypeError",
        "RuntimeError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "PermissionError",
        "FileNotFoundError",
        "UnicodeDecodeError",
        "JSONDecodeError",
        "SSLError",
        "SSLCertVerificationError",
        "ClientError",
        "ClientConnectorError",
        "ClientConnectorCertificateError",
        "ClientConnectorSSLError",
        "ServerDisconnectedError",
        "ClientResponseError",
        "InvalidURL",
        "gaierror",
    }
)
_CODE_REASONS = {
    code: name.removeprefix("CODE_").lower() for name, code in APK_ERROR_CODES.items()
}
_AUTH_REASONS = {
    -202: "account_not_found",
    -203: "incorrect_password",
    -204: "account_not_activated",
    -205: "account_blocked",
    -900: "token_verification_failed",
}
_REASONS = frozenset(
    {
        "unknown_region",
        "http_unauthorized",
        "timeout",
        "invalid_json",
        "network_error",
        "invalid_response",
        "invalid_status_code",
        "invalid_redirect",
        "http_redirect_refused",
        "server_error",
        "invalid_data",
        "product_configuration_download",
        "certificate_download",
        "redirect_limit",
        "app_authorization_rejected",
        "invalid_app_callback",
        "incomplete_app_credentials",
        "account_identity_mismatch",
        "invalid_credential_expiry",
        "expired_app_credentials",
        "invalid_app_session",
        "missing_mqtt_key",
        "invalid_mqtt_certificate",
        "mqtt_publish_failed",
        "mqtt_loop_start_failed",
        "mqtt_shutdown_failed",
        "mqtt_certificate_cleanup_failed",
        "incomplete_mqtt_profile",
    }
)


def safe_code(value: Any) -> int | None:
    """Keep only integral codes, including Paho's numeric reason-code value."""
    return parse_wire_integer(getattr(value, "value", value))


def safe_region(value: Any) -> str:
    return (
        value
        if isinstance(value, str) and value in {*REGIONS, "bootstrap"}
        else "unknown"
    )


def safe_series(value: Any) -> str:
    return value if isinstance(value, str) and value in _SERIES else "unknown"


def safe_picker(value: Any) -> str:
    return value if isinstance(value, str) and value in _PICKERS else "unknown"


def state_fields(values: Iterable[Any]) -> list[str]:
    return sorted(
        key for key in values if isinstance(key, str) and key in SAFE_STATE_FIELDS
    )


def safe_version(value: Any) -> str:
    if isinstance(value, str) and re.fullmatch(
        r"[0-9]{1,3}(?:\.[0-9]{1,5}){1,3}", value
    ):
        return value
    return "unknown"


def _error_type(error: BaseException | None) -> str | None:
    if error is None:
        return None
    name = type(error).__name__
    return name if name in _ERROR_TYPES else "Exception"


def error_info(error: BaseException, *, region: Any = None) -> dict[str, Any]:
    """Only fixed labels, allowlisted names and validated integers escape."""
    code = safe_code(getattr(error, "code", None))
    status = safe_code(getattr(error, "http_status", None))
    reason = getattr(error, "reason", None)
    if not isinstance(reason, str) or reason not in _REASONS:
        reason = _AUTH_REASONS.get(code) or _CODE_REASONS.get(
            code, "no_vendor_code" if code is None else "unrecognised_vendor_code"
        )
    cause = error.__cause__ or error.__context__
    errno = safe_code(getattr(cause or error, "errno", None))
    return {
        "error": _error_type(error),
        "region": safe_region(getattr(error, "region", None) or region),
        "code": code,
        "http_status": status if status is not None and 100 <= status <= 599 else None,
        "reason": reason,
        "cause": _error_type(cause),
        "errno": errno if errno is not None and -4096 <= errno <= 4096 else None,
    }


def error_details(error: BaseException, *, region: Any = None) -> str:
    return " ".join(
        f"{key}={value}" for key, value in error_info(error, region=region).items()
    )


def error_summary(error: BaseException) -> str:
    """A safe setup/retry message even if an upstream exception had secrets."""
    fields = error_info(error)
    return (
        f"Lepro Cloud request failed (region={fields['region']}, "
        f"code={fields['code']}, HTTP status={fields['http_status']}, "
        f"reason={fields['reason']})"
    )


def log_failure(
    logger: logging.Logger,
    level: int,
    event: str,
    error: BaseException,
    *,
    region: Any = None,
    device: int | None = None,
    family: int | None = None,
) -> None:
    """Event strings are code constants; identifiers are session-local ordinals."""
    logger.log(
        level,
        "%s: device=%s family=%s %s",
        event,
        device,
        family,
        error_details(error, region=region),
    )


def device_index(devices: Mapping[str, Any], did: str) -> int | None:
    return next((index for index, key in enumerate(devices, 1) if key == did), None)


def device_details(device: Mapping[str, Any]) -> str:
    reported_type = safe_code(device.get("type"))
    control = safe_code(device.get("control"))
    effective_type = device_type(dict(device))
    return (
        f"series={safe_series(product_series(device))} "
        f"type={effective_type if effective_type in (0, 1, 2, 3) else None} "
        f"control={control if control in range(-1, 8) else None} "
        f"reported_series={safe_series(device.get('series'))} "
        f"reported_type={reported_type if reported_type in (0, 1, 2, 3) else None}"
    )


def rest_operation(path: str) -> str:
    exact = {
        "/user/region": "account_region",
        "/user/login": "password_login",
        "/user/profile": "account_profile",
        "/web/token/region": "app_token_region",
        "/web/token/refresh": "app_token_exchange",
        "/inapp/token": "app_token_renewal",
    }
    if path in exact:
        return exact[path]
    for prefix, label in (
        ("/family/list/", "family_discovery"),
        ("/v3/device/list/", "device_discovery"),
        ("/v3/scene/list/", "scene_list"),
    ):
        if path.startswith(prefix):
            return label
    return "other"
