"""Offline setup routing and structured Lepro rejection diagnostics."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_client_rest_timestamps import (
    FakeResponse,
    RecordingSession,
    _api,
    _load_client_module,
)
from test_config_flow_errors import _ConfigEntries, _entry, _load_config_flow_module


def flow_fixture(module, step):
    entry = _entry(
        entry_id="one",
        username="private@example.invalid",
        password="old-secret",
        region="north_america",
    )
    entries = _ConfigEntries([entry] if step != "email" else [], entry)
    entries.reauth_entry = entry
    flow = module.LeproCloudFlow()
    flow.hass = SimpleNamespace(config_entries=entries, data={})
    return flow, entry, entries


@pytest.mark.parametrize("step", ["email", "reconfigure", "reauth_confirm"])
@pytest.mark.parametrize("region", ["north_america", "europe", "far_east"])
def test_manual_region_bypasses_bootstrap_and_persists(monkeypatch, step, region):
    module = _load_config_flow_module()
    flow, entry, entries = flow_fixture(module, step)
    lookup = AsyncMock(side_effect=AssertionError("manual route called bootstrap"))
    monkeypatch.setattr(module, "_async_account_region", lookup)
    calls = []

    class Api:
        uid = None

        def __init__(self, hass, selected):
            calls.append(selected)

        async def async_login(self, username, password):
            assert username == "private@example.invalid"
            assert password == "private-password"

    monkeypatch.setattr(module, "LeproApi", Api)
    result = asyncio.run(
        getattr(flow, f"async_step_{step}")(
            {
                "username": "private@example.invalid",
                "password": "private-password",
                "region_override": region,
            }
        )
    )
    data = result["data"] if step == "email" else entry.data
    assert data["region"] == region
    assert data["region_override"] == region
    assert calls == [region]
    lookup.assert_not_awaited()
    if step != "email":
        assert entries.reloads == ["one"]


def test_configure_can_return_to_automatic_and_prefills_existing_override(monkeypatch):
    module = _load_config_flow_module()
    flow, entry, _ = flow_fixture(module, "reconfigure")
    entry.data["region_override"] = "europe"
    shown = asyncio.run(flow.async_step_reconfigure())
    fields = {key.key: key.default for key in shown["data_schema"]}
    assert fields["region_override"] == "europe"
    lookup = AsyncMock(return_value="far_east")
    monkeypatch.setattr(module, "_async_account_region", lookup)

    class Api:
        uid = None

        def __init__(self, hass, region):
            assert region == "far_east"

        async def async_login(self, username, password):
            pass

    monkeypatch.setattr(module, "LeproApi", Api)
    asyncio.run(
        flow.async_step_reconfigure(
            {
                "username": "private@example.invalid",
                "password": "private-password",
                "region_override": "auto",
            }
        )
    )
    lookup.assert_awaited_once()
    assert entry.data["region"] == "far_east"
    assert "region_override" not in entry.data


@pytest.mark.parametrize("step", ["email", "reconfigure", "reauth_confirm"])
@pytest.mark.parametrize("stage", ["region_lookup", "login"])
def test_flow_failure_identifies_stage_code_destination_and_redacts(
    monkeypatch, caplog, step, stage
):
    module = _load_config_flow_module()
    flow, _entry_unused, _ = flow_fixture(module, step)
    code = -202 if stage == "region_lookup" else -203
    destination = "bootstrap" if stage == "region_lookup" else "far_east"
    rejection = module.LeproAuthError(
        "private@example.invalid private-password private-token private-secret",
        code=code,
        http_status=401,
        region=destination,
    )
    lookup = AsyncMock(
        side_effect=rejection if stage == "region_lookup" else None,
        return_value="europe",
    )
    monkeypatch.setattr(module, "_async_account_region", lookup)

    class Api:
        def __init__(self, hass, region):
            assert region == "europe"

        async def async_login(self, username, password):
            raise rejection

    monkeypatch.setattr(module, "LeproApi", Api)
    result = asyncio.run(
        getattr(flow, f"async_step_{step}")(
            {
                "username": "private@example.invalid",
                "password": "private-password",
            }
        )
    )
    assert result["errors"] == {"base": "invalid_auth"}
    for expected in (
        f"step={step}",
        f"stage={stage}",
        f"region={destination}",
        f"code={code}",
        "http_status=401",
        "LeproAuthError",
    ):
        assert expected in caplog.text
    for secret in (
        "private@example.invalid",
        "private-password",
        "private-token",
        "private-secret",
    ):
        assert secret not in caplog.text


def test_failed_manual_login_keeps_override_in_form(monkeypatch, caplog):
    module = _load_config_flow_module()
    flow, _, _ = flow_fixture(module, "email")
    lookup = AsyncMock()
    monkeypatch.setattr(module, "_async_account_region", lookup)
    rejection = module.LeproAuthError("private-password", code=-204, http_status=200)

    class Api:
        def __init__(self, hass, region):
            assert region == "europe"

        async def async_login(self, username, password):
            raise rejection

    monkeypatch.setattr(module, "LeproApi", Api)
    result = asyncio.run(
        flow.async_step_email(
            {
                "username": "private@example.invalid",
                "password": "private-password",
                "region_override": "europe",
            }
        )
    )
    fields = {key.key: key.default for key in result["data_schema"]}
    assert fields["region_override"] == "europe"
    assert "stage=login" in caplog.text
    assert "region=europe" in caplog.text
    assert "reason=account_not_activated" in caplog.text
    lookup.assert_not_awaited()


@pytest.mark.parametrize("code", [-202, -203, -204, -205, -900, 401, 1001, 1002])
@pytest.mark.parametrize("status", [200, 401])
def test_actual_request_keeps_auth_code_and_http_status(code, status):
    module = _load_client_module()
    session = RecordingSession(
        [
            FakeResponse(
                {
                    "code": code,
                    "message": "private-password private-token",
                },
                status=status,
            )
        ]
    )
    api = _api(module, session)
    api._host = module.REGIONS["europe"]
    with pytest.raises(module.LeproAuthError) as caught:
        asyncio.run(
            api._request("POST", "/user/login", {"password": "private-password"})
        )
    assert caught.value.code == code
    assert caught.value.http_status == status
    assert caught.value.region == "europe"
    assert "private-password" not in str(caught.value)


def test_redirect_failure_reports_destination_region_and_preserves_request():
    module = _load_client_module()
    session = RecordingSession(
        [
            FakeResponse(
                {"code": -100, "data": {"apiHost": module.REGIONS["far_east"]}}
            ),
            FakeResponse({"code": -202}, status=200),
        ]
    )
    api = _api(module, session)
    api._host = module.REGIONS["europe"]
    data = {"account": "private@example.invalid", "password": "private-password"}
    with pytest.raises(module.LeproAuthError) as caught:
        asyncio.run(api._request("POST", "/user/login", data))
    assert caught.value.region == "far_east"
    assert caught.value.code == -202
    assert [request["url"] for request in session.requests] == [
        f"https://{module.REGIONS['europe']}/user/login",
        f"https://{module.REGIONS['far_east']}/user/login",
    ]
    assert all(request["data"] == data for request in session.requests)


def test_invalid_server_override_never_becomes_a_url(monkeypatch):
    module = _load_config_flow_module()
    flow, _, _ = flow_fixture(module, "email")
    lookup = AsyncMock()
    monkeypatch.setattr(module, "_async_account_region", lookup)
    api = AsyncMock(side_effect=AssertionError("must not construct client"))
    monkeypatch.setattr(module, "LeproApi", api)
    result = asyncio.run(
        flow.async_step_email(
            {
                "username": "private@example.invalid",
                "password": "private-password",
                "region_override": "https://untrusted.invalid",
            }
        )
    )
    assert result["errors"] == {"base": "invalid_response"}
    api.assert_not_called()
    lookup.assert_not_awaited()


def test_login_redirect_stores_actual_region_separately_from_override(monkeypatch):
    module = _load_config_flow_module()
    flow, _, _ = flow_fixture(module, "email")

    class Api:
        uid = None
        region = "far_east"

        def __init__(self, hass, region):
            assert region == "europe"

        async def async_login(self, username, password):
            pass

    monkeypatch.setattr(module, "LeproApi", Api)
    result = asyncio.run(
        flow.async_step_email(
            {
                "username": "private@example.invalid",
                "password": "private-password",
                "region_override": "europe",
            }
        )
    )
    assert result["data"]["region"] == "far_east"
    assert result["data"]["region_override"] == "europe"


@pytest.mark.parametrize("stage", ["region_lookup", "login"])
@pytest.mark.parametrize("status", [200, 401])
def test_real_response_through_setup_to_safe_log(monkeypatch, caplog, stage, status):
    client = _load_client_module()
    module = _load_config_flow_module()
    flow, _, _ = flow_fixture(module, "email")
    code = -202 if stage == "region_lookup" else -203
    replies = [
        FakeResponse(
            {
                "code": code,
                "msg": "private@example.invalid private-password private-token",
            },
            status=status,
        )
    ]
    if stage == "login":
        replies.insert(
            0,
            FakeResponse(
                {
                    "code": 0,
                    "data": {"apiHost": client.REGIONS["europe"]},
                }
            ),
        )
    session = RecordingSession(replies)
    monkeypatch.setattr(client, "async_get_clientsession", lambda hass: session)
    # Only an import stub providing the installation ID; no HA instance.
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.instance_id",
        SimpleNamespace(async_get=AsyncMock(return_value="fixture-install")),
    )
    result = asyncio.run(
        flow.async_step_email(
            {
                "username": "private@example.invalid",
                "password": "private-password",
            }
        )
    )
    assert result["errors"] == {"base": "invalid_auth"}
    destination = "bootstrap" if stage == "region_lookup" else "europe"
    for expected in (
        f"stage={stage}",
        f"code={code}",
        f"http_status={status}",
        f"region={destination}",
    ):
        assert expected in caplog.text
    assert (
        session.requests[0]["url"]
        == f"https://{client.REGION_DISCOVERY_HOST}/user/region"
    )
    if stage == "login":
        assert (
            session.requests[1]["url"]
            == f"https://{client.REGIONS['europe']}/user/login"
        )
    for secret in ("private@example.invalid", "private-password", "private-token"):
        assert secret not in caplog.text


@pytest.mark.parametrize("status", [401, 500])
def test_non_json_error_reports_actual_status_without_inventing_code(status):
    client = _load_client_module()

    class InvalidJsonResponse(FakeResponse):
        async def json(self, **kwargs):
            raise ValueError("private-token in invalid response")

    api = _api(client, RecordingSession([InvalidJsonResponse(None, status=status)]))
    api._host = client.REGIONS["far_east"]
    expected = client.LeproAuthError if status == 401 else client.LeproApiError
    with pytest.raises(expected) as caught:
        asyncio.run(api._request("POST", "/user/login"))
    assert caught.value.code is None
    assert caught.value.http_status == status
    assert caught.value.region == "far_east"
    assert "private-token" not in str(caught.value)


@pytest.mark.parametrize("code", [None, True, -203.5, "private-password"])
def test_invalid_vendor_status_is_not_misreported_as_a_password_rejection(code):
    client = _load_client_module()
    api = _api(client, RecordingSession([FakeResponse({"code": code}, status=200)]))
    api._host = client.REGIONS["europe"]
    with pytest.raises(client.LeproResponseError) as caught:
        asyncio.run(api._request("POST", "/user/login"))
    assert caught.value.code is None
    assert caught.value.http_status == 200
    assert caught.value.region == "europe"
    assert "private-password" not in str(caught.value)


def test_untrusted_redirect_is_not_followed_and_reports_original_region():
    client = _load_client_module()
    session = RecordingSession(
        [
            FakeResponse(
                {
                    "code": -100,
                    "data": {"apiHost": "untrusted.invalid"},
                }
            )
        ]
    )
    api = _api(client, session)
    api._host = client.REGIONS["europe"]
    with pytest.raises(client.LeproResponseError) as caught:
        asyncio.run(api._request("POST", "/user/login"))
    assert caught.value.code == -100
    assert caught.value.region == "europe"
    assert caught.value.http_status == 200
    assert len(session.requests) == 1


def test_timeout_after_http_headers_retains_known_status():
    client = _load_client_module()

    class SlowBody(FakeResponse):
        async def json(self, **kwargs):
            raise TimeoutError("private-response")

    api = _api(client, RecordingSession([SlowBody(None, status=200)]))
    api._host = client.REGIONS["europe"]
    with pytest.raises(client.LeproApiError) as caught:
        asyncio.run(api._request("POST", "/user/login"))
    assert caught.value.http_status == 200
    assert caught.value.code is None
    assert caught.value.reason == "timeout"
    assert caught.value.region == "europe"


def test_server_selector_is_optional_and_has_friendly_labels():
    module = _load_config_flow_module()
    schema = module._credentials_schema()
    marker = next(key for key in schema if key.key == "region_override")
    assert type(marker).__name__ == "OptionalMarker"
    assert marker.default == "auto"
    selector = schema[marker]
    assert selector["options"] == [
        {"value": "auto", "label": "Automatic"},
        {"value": "north_america", "label": "North America"},
        {"value": "europe", "label": "Europe"},
        {"value": "far_east", "label": "Far East"},
    ]


def test_unknown_bootstrap_region_keeps_success_code_and_http_status(monkeypatch):
    client = _load_client_module()
    session = RecordingSession(
        [
            FakeResponse(
                {
                    "code": 0,
                    "data": {"apiHost": "untrusted.invalid"},
                },
                status=200,
            )
        ]
    )
    monkeypatch.setattr(client, "async_get_clientsession", lambda hass: session)
    with pytest.raises(client.LeproResponseError) as caught:
        asyncio.run(
            client.LeproApi.async_resolve_region(None, "private@example.invalid")
        )
    assert caught.value.code == 0
    assert caught.value.http_status == 200
    assert caught.value.region == "bootstrap"
    assert caught.value.reason == "unknown_region"
