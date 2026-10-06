"""Tests for private Lepro MQTT key loading."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_KEY_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "lepro_cloud"
    / "mqtt_key.py"
)
_SPEC = spec_from_file_location("lepro_cloud_mqtt_key", _KEY_PATH)
assert _SPEC and _SPEC.loader
mqtt_key = module_from_spec(_SPEC)
_SPEC.loader.exec_module(mqtt_key)


def test_load_mqtt_private_key_from_configured_private_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "mqtt_client_key.pem"
    key_file.write_text("placeholder-test-material\n", encoding="utf-8")
    monkeypatch.setenv(mqtt_key.ENV_MQTT_KEY_FILE, str(key_file))
    monkeypatch.setattr(mqtt_key, "_is_private_key_pem", lambda value: True)

    loaded = mqtt_key.load_mqtt_private_key()

    assert loaded == "placeholder-test-material\n"


def test_load_mqtt_private_key_rejects_non_pem_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "mqtt_client_key.pem"
    key_file.write_text("not a key", encoding="utf-8")
    monkeypatch.setenv(mqtt_key.ENV_MQTT_KEY_FILE, str(key_file))

    with pytest.raises(mqtt_key.MqttKeyError, match="not PEM-formatted"):
        mqtt_key.load_mqtt_private_key()
