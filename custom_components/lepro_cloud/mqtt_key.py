"""Private Lepro MQTT client-key loading."""

from __future__ import annotations

import os
from pathlib import Path

ENV_MQTT_KEY_FILE = "LEPRO_MQTT_CLIENT_KEY_FILE"
PACKAGE_PRIVATE_KEY = Path(__file__).resolve().parent / "_private" / "mqtt_client_key.pem"
WORKSPACE_PRIVATE_KEY = Path.cwd() / ".lepro_private" / "mqtt_client_key.pem"


class MqttKeyError(Exception):
    """The private MQTT client key is unavailable or invalid."""


def _is_private_key_pem(value: str) -> bool:
    return (
        "-----BEGIN PRIVATE KEY-----" in value
        and "-----END PRIVATE KEY-----" in value
    ) or (
        "-----BEGIN RSA PRIVATE KEY-----" in value
        and "-----END RSA PRIVATE KEY-----" in value
    )


def mqtt_private_key_candidates() -> tuple[Path, ...]:
    """Return private key locations in lookup order."""
    configured = os.environ.get(ENV_MQTT_KEY_FILE)
    paths: list[Path] = []
    if configured:
        paths.append(Path(configured).expanduser())
    paths.extend((PACKAGE_PRIVATE_KEY, WORKSPACE_PRIVATE_KEY))
    return tuple(paths)


def load_mqtt_private_key() -> str:
    """Load the APK-derived static app MQTT private key from a private file."""
    for path in mqtt_private_key_candidates():
        if not path.is_file():
            continue
        key = path.read_text(encoding="utf-8").strip()
        if not _is_private_key_pem(key):
            raise MqttKeyError(f"Lepro MQTT private key file is not PEM-formatted: {path}")
        return f"{key}\n"
    raise MqttKeyError(
        "Lepro MQTT private key is missing; place the private APK-derived key in "
        f"{PACKAGE_PRIVATE_KEY} or set {ENV_MQTT_KEY_FILE}"
    )
