"""Account-region routing and OAuth renewal checks, with no HA instance."""

from __future__ import annotations

import asyncio
import base64
import logging
import sys
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_client_rest_timestamps import (
    FakeResponse,
    RecordingSession,
    _api,
    _load_client_module,
)
from test_config_flow_errors import _load_config_flow_module

PRIVATE = "private-account-token"
APP_TOKEN = base64.b64encode(bytes([251]) * 96).decode()


def load_app():
    _load_config_flow_module()
    client = sys.modules["custom_components.lepro_cloud.client"]
    oauth = sys.modules["homeassistant.helpers.config_entry_oauth2_flow"]
    oauth.LocalOAuth2Implementation = object
    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components/lepro_cloud/app_auth.py"
    )
    spec = spec_from_file_location("custom_components.lepro_cloud.app_auth", path)
    app = module_from_spec(spec)
    sys.modules[spec.name] = app
    spec.loader.exec_module(app)
    return client, app


@pytest.mark.parametrize("region", ["north_america", "europe", "far_east"])
def test_account_bootstrap_uses_vendor_api_host_not_ha_country(monkeypatch, region):
    client = _load_client_module()
    session = RecordingSession(
        [
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "apiHost": client.REGIONS[region],
                        "apiDeviceHost": "not-the-account-api.invalid",
                    },
                }
            )
        ]
    )
    monkeypatch.setattr(client, "async_get_clientsession", lambda hass: session)
    hass = SimpleNamespace(config=SimpleNamespace(country="unrelated-country"))
    selected = asyncio.run(
        client.LeproApi.async_resolve_region(hass, "private@example.invalid")
    )
    assert selected == region
    request = session.requests[0]
    assert request["url"] == f"https://{client.REGION_DISCOVERY_HOST}/user/region"
    assert set(request["data"]) == {"account", "timestamp"}
    assert request["allow_redirects"] is False


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_http_redirect_cannot_forward_password_or_custom_token_header(status, caplog):
    client = _load_client_module()
    response = FakeResponse(None, status=status)
    response.headers = {"Location": f"https://{PRIVATE}.invalid/"}
    session = RecordingSession([response])
    api = _api(client, session)
    api._host = client.REGIONS["europe"]
    api.token = PRIVATE
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(client.LeproResponseError) as caught,
    ):
        asyncio.run(api._request("POST", "/user/login", {"password": PRIVATE}))
    assert caught.value.http_status == status
    assert caught.value.reason == "http_redirect_refused"
    assert len(session.requests) == 1
    assert session.requests[0]["allow_redirects"] is False
    assert PRIVATE not in caplog.text
    assert "operation=password_login" in caplog.text


def test_body_host_updates_are_allowlisted_and_bounded(caplog):
    client = _load_client_module()
    session = RecordingSession(
        [
            FakeResponse(
                {"code": -100, "data": {"apiHost": client.REGIONS["far_east"]}}
            ),
            FakeResponse(
                {"code": -100, "data": {"apiHost": client.REGIONS["north_america"]}}
            ),
        ]
    )
    api = _api(client, session)
    api._host = client.REGIONS["europe"]
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(client.LeproResponseError) as caught,
    ):
        asyncio.run(api._request("GET", "/user/profile"))
    assert len(session.requests) == 2
    assert api.region == "far_east"
    assert caught.value.code == -100 and caught.value.reason == "redirect_limit"
    assert "from_region=europe to_region=far_east" in caplog.text
    assert all(request["allow_redirects"] is False for request in session.requests)


def exchange_replies(client, target, phase):
    data = [
        {"apiHost": client.REGIONS["europe"]},
        {
            "uid": PRIVATE,
            "token": "private-access",
            "secret": "private-mqtt",
            "expire": int(time.time()) + 90000,
        },
        {"uid": PRIVATE, "username": "private@example.invalid"},
        {"userToken": APP_TOKEN, "tokenExpire": int(time.time()) + 80000},
    ]
    replies = [FakeResponse({"code": 0, "data": value}) for value in data]
    replies.insert(
        phase,
        FakeResponse(
            {
                "code": -100,
                "data": {"apiHost": client.REGIONS[target]},
            }
        ),
    )
    return replies


@pytest.mark.parametrize("target", ["north_america", "far_east"])
@pytest.mark.parametrize("phase", [1, 2, 3])
@pytest.mark.parametrize("renewal", [False, True])
def test_app_session_persists_final_region_after_vendor_migration(
    monkeypatch, caplog, target, phase, renewal
):
    client, app = load_app()
    session = RecordingSession(exchange_replies(client, target, phase))
    monkeypatch.setattr(client, "async_get_clientsession", lambda hass: session)
    with caplog.at_level(logging.DEBUG):
        token = asyncio.run(
            app.async_exchange_app_token(
                None,
                APP_TOKEN,
                expected_uid=PRIVATE if renewal else None,
            )
        )
    assert token["region"] == target
    assert (
        session.requests[-1]["url"] == f"https://{client.REGIONS[target]}/inapp/token"
    )
    assert all(request["allow_redirects"] is False for request in session.requests)
    for secret in (
        PRIVATE,
        "private-access",
        "private-mqtt",
        "private@example.invalid",
        APP_TOKEN,
    ):
        assert secret not in caplog.text
    assert f"region={target}" in caplog.text


@pytest.mark.parametrize("phase", [0, 1])
def test_app_rejection_keeps_code_and_exchange_stage_without_token(
    monkeypatch, caplog, phase
):
    client, app = load_app()
    replies = [FakeResponse({"code": -101}, status=200)]
    if phase == 1:
        replies.insert(
            0, FakeResponse({"code": 0, "data": {"apiHost": client.REGIONS["europe"]}})
        )
    session = RecordingSession(replies)
    monkeypatch.setattr(client, "async_get_clientsession", lambda hass: session)
    with caplog.at_level(logging.DEBUG), pytest.raises(client.LeproAuthError) as caught:
        asyncio.run(app.async_exchange_app_token(None, APP_TOKEN))
    assert caught.value.code == -101
    assert caught.value.http_status == 200
    assert caught.value.reason == "app_authorization_rejected"
    assert "code=-101" in caplog.text
    assert (
        "operation=app_token_region" if phase == 0 else "operation=app_token_exchange"
    ) in caplog.text
    assert APP_TOKEN not in caplog.text


def test_restoring_same_app_token_does_not_undo_a_validated_migration():
    client, app = load_app()
    token = {
        "uid": PRIVATE,
        "access_token": "private-access",
        "secret": "private-mqtt",
        "region": "europe",
        "expires_at": int(time.time()) + 90000,
    }
    api = app.LeproAppApi.__new__(app.LeproAppApi)
    api._entry = SimpleNamespace(data={"token": token})
    api._oauth = SimpleNamespace(token=token, async_ensure_token_valid=AsyncMock())
    api.token = "private-access"
    api._host = client.REGIONS["far_east"]
    asyncio.run(api.async_restore_session())
    assert api.region == "far_east"


def test_api_operations_and_paths_do_not_leak_device_or_family_identifiers(caplog):
    client = _load_client_module()
    api = _api(client, RecordingSession([FakeResponse({"code": -904}, status=403)]))
    api._host = client.REGIONS["europe"]
    with caplog.at_level(logging.DEBUG), pytest.raises(client.LeproResponseError):
        asyncio.run(
            api._request("GET", f"/v3/scene/list/fid/{PRIVATE}/did/{PRIVATE}/cid/0")
        )
    assert "operation=scene_list" in caplog.text
    assert "code=-904" in caplog.text
    assert PRIVATE not in caplog.text
