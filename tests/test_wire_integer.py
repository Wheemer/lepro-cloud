"""APK numeric representation regressions; no Home Assistant runtime."""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_platform_devices import _load_module


@pytest.mark.parametrize("value", [500, 500.0, "500", "500.0", "5e2", "0500"])
def test_integral_wire_representations(value):
    protocol = _load_module("protocol")
    assert protocol.parse_wire_integer(value) == 500


@pytest.mark.parametrize("value", [None, True, 1.5, "1.5", "nan", "inf", "1_000", [], 2**31])
def test_invalid_integer_is_not_truncated(value):
    protocol = _load_module("protocol")
    assert protocol.parse_wire_integer(value) is None


def test_discovery_accepts_app_integer_representations():
    device = _load_module("device")
    assert device.is_light({"type": "1.0", "control": 2.0, "series": "E1-30"})
    assert not device.is_light({"type": 1.5, "control": 2})
    assert not device.is_light({"type": 1, "control": 2.5})


def test_actual_mqtt_callback_keeps_integral_decimal_report():
    client = _load_module("client")

    async def run():
        coordinator = client.LeproCoordinator.__new__(client.LeproCoordinator)
        coordinator._stopping = False
        coordinator.devices = {"123": {"series": "E1-30"}}
        coordinator.hass = SimpleNamespace(loop=asyncio.get_running_loop())
        coordinator._record_property_message = Mock()
        coordinator._apply_report = Mock()
        coordinator._on_message(
            None, None,
            SimpleNamespace(
                topic="le/123/prp/getr",
                payload=json.dumps({"d": {
                    "online": 1.0, "d1": 1.0, "d2": "2.0",
                    "d50": "native-pattern", "d52": 500.0, "d53": "30.0",
                }}).encode(),
            ),
        )
        await asyncio.sleep(0)
        coordinator._apply_report.assert_called_once()
        did, state = coordinator._apply_report.call_args.args
        assert did == "123"
        assert state == {
            "online": 1, "d1": 1, "d2": 2, "d50": "native-pattern",
            "d52": 500, "d53": 30,
        }

    asyncio.run(run())


def test_decimal_success_response_does_not_trigger_requery():
    client = _load_module("client")
    coordinator = client.LeproCoordinator.__new__(client.LeproCoordinator)
    coordinator._command_lock = threading.Lock()
    coordinator._pending_commands = {123: ("123", 0)}
    coordinator._query_device = Mock()
    coordinator._command_response("123", "123.0", 0.0)
    assert coordinator._pending_commands == {}
    coordinator._query_device.assert_not_called()


@pytest.mark.parametrize("control", [2, 3, 6, 7])
def test_apk_mqtt_control_variants_reach_light_platform(control):
    device = _load_module("device")
    assert device.is_light({"type": 1, "control": control, "series": "E1-30"})
    assert not device.is_supported_device({"type": 3, "control": control})


@pytest.mark.parametrize("control", [-1, 0, 1, 4, 5, 8])
def test_non_mqtt_transports_are_not_cloud_lights(control):
    device = _load_module("device")
    assert not device.is_light({"type": 1, "control": control, "series": "E1-30"})
