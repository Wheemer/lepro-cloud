"""Whole-integration log redaction and runtime failure diagnostics, without HA."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_platform_devices import _load_module

PRIVATE = "private-password-token-credential"
DID = "private-device-id"
FID = "private-family-id"


def test_structured_failure_never_formats_exception_text_or_untrusted_fields(caplog):
    client = _load_module("client")
    logs = _load_module("log_helpers")
    error = client.LeproResponseError(
        PRIVATE,
        code=-904,
        http_status=403,
        region="europe",
        reason=PRIVATE,
    )
    try:
        raise OSError(2, PRIVATE, f"/private/{PRIVATE}.pem")
    except OSError as cause:
        error.__cause__ = cause
    with caplog.at_level(logging.DEBUG):
        logs.log_failure(
            logging.getLogger("audit"),
            logging.DEBUG,
            "Scene request failed",
            error,
            device=1,
            family=2,
        )
    assert "device=1 family=2" in caplog.text
    assert "code=-904" in caplog.text and "http_status=403" in caplog.text
    assert "region=europe" in caplog.text and "errno=2" in caplog.text
    assert PRIVATE not in caplog.text


def test_unknown_metadata_is_not_echoed_by_setup_summaries(caplog):
    light = _load_module("light")
    switch = _load_module("switch")
    co = SimpleNamespace(
        devices={
            DID: {"type": 1, "control": 2, "series": PRIVATE, "_color_picker": PRIVATE},
            "other-private-device": {"type": 2, "control": 3, "series": PRIVATE},
        },
        states={DID: {PRIVATE: PRIVATE, "d1234567890": PRIVATE}},
        effect_types={},
    )

    async def run():
        with caplog.at_level(logging.DEBUG):
            await light.async_setup_entry(
                None, SimpleNamespace(runtime_data=co), lambda es: list(es)
            )
            await switch.async_setup_entry(
                None, SimpleNamespace(runtime_data=co), lambda es: list(es)
            )

    asyncio.run(run())
    assert "device=1" in caplog.text and "device=2" in caplog.text
    assert "series=unknown" in caplog.text
    for secret in (PRIVATE, DID, "other-private-device", "d1234567890"):
        assert secret not in caplog.text


def test_scene_cache_failures_have_safe_family_context(caplog):
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    device = {"did": DID, "series": "E1-30", "_family_ids": [FID]}
    co.devices = {DID: device}
    co._collect_scene_pages = AsyncMock(
        side_effect=client.LeproResponseError(
            PRIVATE, code=-904, http_status=403, region="europe"
        )
    )
    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(co._async_device_scenes(device)) == []
    assert "device=1 family=1" in caplog.text
    assert "code=-904" in caplog.text
    for secret in (PRIVATE, DID, FID):
        assert secret not in caplog.text


def test_outer_scene_failure_does_not_echo_identifiers_or_exception(caplog):
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co.devices = {DID: {"did": DID}}
    co._async_device_scenes = AsyncMock(side_effect=ValueError(PRIVATE))
    with caplog.at_level(logging.DEBUG):
        asyncio.run(co._load_device_scenes())
    assert "device=1" in caplog.text and "error=ValueError" in caplog.text
    assert PRIVATE not in caplog.text and DID not in caplog.text


class Reason:
    value = 135
    is_failure = True

    def __str__(self):
        return PRIVATE


@pytest.mark.parametrize("callback", ["connect", "disconnect", "subscribe"])
def test_mqtt_reason_objects_log_numeric_code_not_string(caplog, callback):
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    transport = object()
    co.client = transport
    co._stopping = False
    co.devices = {DID: {"series": "E1-30"}}
    co._set_transport_state = Mock()
    co._request_refresh = Mock()
    co.hass = SimpleNamespace(
        loop=SimpleNamespace(call_soon_threadsafe=lambda fn, *a: fn(*a))
    )
    with caplog.at_level(logging.DEBUG):
        if callback == "connect":
            co._on_connect(transport, None, None, Reason(), None)
        elif callback == "disconnect":
            co._on_disconnect(transport, None, None, Reason(), None)
        else:
            co._on_subscribe(transport, None, 1, [Reason()], None)
    assert "135" in caplog.text
    assert PRIVATE not in caplog.text and DID not in caplog.text


def test_command_rejection_has_numeric_code_and_anonymous_device(caplog):
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co.devices = {DID: {"series": "E1-30", "type": 1, "control": 3}}
    co._command_lock = threading.Lock()
    co._pending_commands = {123: (DID, 0)}
    co._query_device = Mock()
    with caplog.at_level(logging.DEBUG):
        co._command_response(DID, 123, 135)
    assert "device=1 code=135" in caplog.text
    assert "series=E1-30" in caplog.text and DID not in caplog.text
    co._query_device.assert_called_once_with(DID)


@pytest.mark.parametrize("mode", ["library_error", "queue_error"])
def test_state_query_failure_is_visible_without_raw_exception(mode, caplog):
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co.devices = {DID: {"series": "E1-30", "type": 1}}
    co.effect_types = {}
    co.states = {}
    transport = SimpleNamespace(
        publish=Mock(
            side_effect=RuntimeError(PRIVATE) if mode == "library_error" else None,
            return_value=SimpleNamespace(rc=7),
        )
    )
    with caplog.at_level(logging.DEBUG):
        assert not co._publish_state_query(transport, DID)
    assert "device=1" in caplog.text
    assert PRIVATE not in caplog.text and DID not in caplog.text
    assert co.states == {}
    if mode == "queue_error":
        assert "code=7" in caplog.text


def test_command_library_exception_is_sanitized_even_in_traceback(caplog):
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co.devices = {DID: {"series": "E1-30"}}
    co.client = SimpleNamespace(publish=Mock(side_effect=RuntimeError(PRIVATE)))
    co.connected = True
    co._stopping = False
    co._command_lock = threading.Lock()
    co._pending_commands = {}
    with caplog.at_level(logging.DEBUG), pytest.raises(client.LeproMqttError) as caught:
        co.command(DID, {"d1": 1})
    rendered = "".join(traceback.format_exception(caught.value))
    assert PRIVATE not in caplog.text and PRIVATE not in rendered
    assert DID not in caplog.text
    assert co._pending_commands == {}


@pytest.mark.parametrize("auth", [False, True])
def test_maintenance_failures_log_details_without_exception_text(auth, caplog):
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co._stopping = False
    co._reauth_requested = False
    co.api = SimpleNamespace(region="far_east")
    co._last_refresh = time.monotonic() - 100
    co._require_reauth = AsyncMock()

    async def fail():
        if auth:
            raise client.LeproAuthError(
                PRIVATE, code=-900, http_status=401, region="far_east"
            )
        co._stopping = True
        raise client.LeproApiError(
            PRIVATE, code=-901, http_status=500, region="far_east"
        )

    co._refresh_session = fail

    async def run():
        co._refresh_requested = asyncio.Event()
        co._refresh_requested.set()
        await co._maintain_session()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(run())
    assert "region=far_east" in caplog.text
    assert PRIVATE not in caplog.text
    if auth:
        assert "code=-900" in caplog.text
        co._require_reauth.assert_awaited_once()
    else:
        assert "code=-901" in caplog.text and "delay_seconds=300" in caplog.text


@pytest.mark.parametrize(
    "data",
    [
        b"private-invalid-json",
        json.dumps({"d": {"online": PRIVATE, "d50": PRIVATE}}).encode(),
        json.dumps({"d": {"d50": PRIVATE, "d52": 500}}).encode(),
        json.dumps({"d": PRIVATE}).encode(),
    ],
)
def test_mqtt_packet_debug_output_never_contains_raw_data(data, caplog):
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co._stopping = False
    co.devices = {DID: {"series": "E1-30"}}
    co._record_property_message = Mock()
    co._apply_report = Mock()
    co.hass = SimpleNamespace(
        loop=SimpleNamespace(call_soon_threadsafe=lambda fn, *a: fn(*a))
    )
    with caplog.at_level(logging.DEBUG):
        co._on_message(
            None, None, SimpleNamespace(topic=f"le/{DID}/prp/rpt", payload=data)
        )
    assert "Lepro MQTT" in caplog.text
    assert PRIVATE not in caplog.text and DID not in caplog.text
    assert "private-invalid-json" not in caplog.text


def test_diagnostics_allowlists_model_firmware_region_and_datapoints():
    diagnostics = _load_module("diagnostics")
    co = SimpleNamespace(
        connected=True,
        api=SimpleNamespace(region=PRIVATE),
        _fresh={DID},
        devices={
            DID: {
                "series": PRIVATE,
                "name": PRIVATE,
                "fwVersion": PRIVATE,
                "control": PRIVATE,
                "scenes": PRIVATE,
            }
        },
        states={DID: {PRIVATE: PRIVATE, "d1234567890": PRIVATE, "d50": PRIVATE}},
    )
    result = asyncio.run(
        diagnostics.async_get_config_entry_diagnostics(
            None,
            SimpleNamespace(
                runtime_data=co, data={"region": PRIVATE, "password": PRIVATE}
            ),
        )
    )
    rendered = json.dumps(result)
    assert PRIVATE not in rendered and DID not in rendered
    assert "d1234567890" not in rendered
    assert result["devices"][0]["datapoints"] == ["d50"]
    assert result["devices"][0]["scene_count"] == 0


def test_private_key_decode_error_does_not_reveal_key_bytes():
    key = _load_module("mqtt_key")

    class Unreadable:
        def is_file(self):
            return True

        def read_text(self, **kwargs):
            raise UnicodeDecodeError("utf-8", PRIVATE.encode(), 0, 1, PRIVATE)

    key.mqtt_private_key_candidates = lambda: (Unreadable(),)
    with pytest.raises(key.MqttKeyError) as caught:
        key.load_mqtt_private_key()
    assert PRIVATE not in "".join(traceback.format_exception(caught.value))


def test_certificate_failure_logs_role_and_status_without_signed_url(caplog):
    from test_client_rest_timestamps import FakeResponse, RecordingSession, _api

    client = _load_module("client")
    api = _api(client, RecordingSession([FakeResponse({}, status=403)]))
    api._host = client.REGIONS["europe"]
    api.token = PRIVATE
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co.api = api
    with caplog.at_level(logging.DEBUG), pytest.raises(client.LeproApiError):
        asyncio.run(
            co._resolve_certs(
                {
                    "root": f"https://{client.REGIONS['europe']}/cert?token={PRIVATE}",
                    "cert": PRIVATE,
                },
                PRIVATE,
                PRIVATE,
            )
        )
    assert "root certificate resolution failed" in caplog.text
    assert "http_status=403" in caplog.text
    assert PRIVATE not in caplog.text and "/cert?" not in caplog.text


@pytest.mark.parametrize("auth", [False, True])
def test_setup_exception_and_logs_never_echo_unstructured_error(
    monkeypatch, caplog, auth
):
    from test_setup_lifecycle import FakeEntry, FakeHass, _load_integration_module

    module = _load_integration_module()
    original = module.LeproCoordinator
    error_cls = module.LeproAuthError if auth else module.LeproApiError

    class Failed(original):
        async def async_start(self):
            raise error_cls(PRIVATE)

    monkeypatch.setattr(module, "LeproCoordinator", Failed)
    expected = module.ConfigEntryAuthFailed if auth else module.ConfigEntryNotReady
    with caplog.at_level(logging.DEBUG), pytest.raises(expected) as caught:
        asyncio.run(module.async_setup_entry(FakeHass(), FakeEntry()))
    assert PRIVATE not in caplog.text
    assert PRIVATE not in "".join(traceback.format_exception(caught.value))
    assert "reason=" in str(caught.value)


def test_shutdown_failure_is_sanitized_and_still_cleans_certificates(caplog):
    from test_platform_devices import FakeHass

    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co.hass = FakeHass()
    co._stopping = True
    co._cancel_initial_state_retry = Mock()
    co.client = SimpleNamespace(
        disconnect=Mock(), loop_stop=Mock(side_effect=RuntimeError(PRIVATE))
    )
    co.tmp = SimpleNamespace(cleanup=Mock())
    cleanup = co.tmp.cleanup
    with caplog.at_level(logging.DEBUG), pytest.raises(client.LeproMqttError) as caught:
        asyncio.run(co._stop_transport())
    cleanup.assert_called_once()
    assert caught.value.reason == "mqtt_shutdown_failed"
    assert PRIVATE not in caplog.text
    assert PRIVATE not in "".join(traceback.format_exception(caught.value))


def test_logger_calls_do_not_regress_to_raw_exceptions_or_identifiers():
    root = Path(__file__).resolve().parents[1] / "custom_components/lepro_cloud"
    forbidden = {
        "err",
        "error",
        "exception",
        "did",
        "fid",
        "reason_code",
        "payload",
        "url",
        "token",
    }
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id not in {
                "_LOGGER",
                "logger",
            }:
                continue
            assert node.func.attr != "exception", f"{path.name}:{node.lineno}"
            assert not any(kw.arg == "exc_info" for kw in node.keywords)
            for argument in node.args:
                assert not (
                    isinstance(argument, ast.Name) and argument.id in forbidden
                ), (path.name, node.lineno, ast.dump(argument))


@pytest.mark.parametrize(
    "state, filtered, rejected",
    [
        ({"d50": PRIVATE, "d52": 500}, 0, 0),
        ({"d1": 1, PRIVATE: PRIVATE}, 1, 0),
        ({"online": PRIVATE, "d50": PRIVATE}, 2, 1),
    ],
)
def test_validation_counters_exclude_inferred_fields(state, filtered, rejected, caplog):
    client = _load_module("client")
    co = client.LeproCoordinator.__new__(client.LeproCoordinator)
    co._stopping = False
    co.devices = {DID: {"series": "E1-30"}}
    co._record_property_message = Mock()
    co._apply_report = Mock()
    co.hass = SimpleNamespace(
        loop=SimpleNamespace(call_soon_threadsafe=lambda fn, *a: fn(*a))
    )
    with caplog.at_level(logging.DEBUG):
        co._on_message(
            None,
            None,
            SimpleNamespace(
                topic=f"le/{DID}/prp/rpt",
                payload=json.dumps({"d": state}).encode(),
            ),
        )
    assert getattr(co, "_filtered_state_fields", 0) == filtered
    assert getattr(co, "_rejected_state_reports", 0) == rejected
    assert "rejected_fields=-" not in caplog.text
    assert PRIVATE not in caplog.text
    if not rejected:
        assert (
            "wire_datapoints=" in caplog.text and "inferred_datapoints=" in caplog.text
        )


def test_downloaded_diagnostics_explains_verified_e1_classification_recovery():
    diagnostics = _load_module("diagnostics")
    co = SimpleNamespace(
        connected=True,
        api=SimpleNamespace(region="far_east"),
        _fresh={DID},
        devices={
            DID: {
                "series": "D1",
                "proId": 68,
                "type": 2,
                "control": 3,
                "fwVersion": "2.3.18",
                "_family_ids": [FID],
            }
        },
        states={DID: {"d50": PRIVATE, "d52": 500}},
    )
    result = asyncio.run(
        diagnostics.async_get_config_entry_diagnostics(
            None,
            SimpleNamespace(
                runtime_data=co,
                data={
                    "region": "europe",
                    "region_override": "europe",
                },
            ),
        )
    )
    assert result["region"] == "europe" and result["active_region"] == "far_east"
    assert result["region_selection"] == "override"
    device = result["devices"][0]
    assert device["series"] == "E1-30" and device["reported_series"] == "D1"
    assert device["type"] == 1 and device["reported_type"] == 2
    assert device["picker"] == "diyEaves"
    assert device["family_context_count"] == 1
    assert device["firmware"] == "2.3.18"
    assert all(secret not in json.dumps(result) for secret in (PRIVATE, DID, FID))
