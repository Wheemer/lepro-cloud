"""Offline app-auth regressions with real HA OAuth/session classes.

Run in the isolated server HA test containers; these tests never log into Lepro.
The live protocol proof is stored separately outside the repository.
"""

import asyncio
import base64
import inspect
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, "/source")
from homeassistant.core import HomeAssistant

# isort: split

from homeassistant import loader
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryDisabler

from custom_components.lepro_cloud import app_auth, client, config_flow

APP_TOKEN = base64.b64encode(bytes([251]) * 96).decode()


class Response:
    status = 200

    def __init__(self, data, code=0, status=200):
        self.data = data
        self.code = code
        self.status = status

    async def json(self, **kwargs):
        return {"code": self.code, "data": self.data}


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected extra HTTP request")
        return self.responses.pop(0)


def exchange_responses(uid="account", region="api-eu-iot.lepro.com"):
    return [
        Response({"apiHost": region}),
        Response(
            {
                "token": "new-bearer",
                "secret": "new-mqtt-secret",
                "uid": uid,
                "expire": int(time.time()) + 86400 * 90,
            }
        ),
        Response({"uid": uid, "username": "person@example.invalid"}),
        Response(
            {"userToken": APP_TOKEN, "tokenExpire": int(time.time()) + 86400 * 30}
        ),
    ]


class AppAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        path = Path("/audit/app-auth") / str(time.time_ns())
        path.mkdir(parents=True)
        self.hass = HomeAssistant(str(path))
        loader.async_setup(self.hass)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()

    async def asyncTearDown(self):
        await self.hass.async_stop()

    async def exchange(self, session, token=APP_TOKEN, **kwargs):
        with patch.object(client, "async_get_clientsession", return_value=session):
            return await app_auth.async_exchange_app_token(self.hass, token, **kwargs)

    async def test_code_exchange_routes_json_and_uses_expiry_of_shorter_token(self):
        session = Session(exchange_responses())
        token = await self.exchange(session)
        self.assertEqual(token["access_token"], "new-bearer")
        self.assertEqual(token["uid"], "account")
        self.assertEqual(token["region"], "europe")
        self.assertLessEqual(token["expires_in"], 86400 * 30 - 3600)
        self.assertGreater(token["expires_in"], 86400 * 29)
        region_request, login_request, profile_request, successor_request = (
            session.requests
        )
        self.assertIn("api-iot.lepro.com/web/token/region", region_request[1])
        self.assertIn("api-eu-iot.lepro.com/web/token/refresh", login_request[1])
        for request in [region_request, login_request]:
            self.assertNotIn("Authorization", request[2]["headers"])
            self.assertNotIn("token", request[2]["headers"])
            self.assertEqual(request[2]["json"]["platform"], "2")
            self.assertEqual(
                request[2]["json"]["thirdToken"], app_auth._wrap_app_token(APP_TOKEN)
            )
            self.assertNotIn("data", request[2])
        self.assertEqual(profile_request[2]["headers"]["token"], "new-bearer")
        self.assertEqual(successor_request[2]["headers"]["token"], "new-bearer")
        self.assertFalse(any("password" in str(r[2]) for r in session.requests))

    async def test_callback_preserves_base64_plus_after_standard_query_parsing(self):
        parsed = parse_qs("code=" + APP_TOKEN)["code"][0]
        self.assertIn(" ", parsed)
        impl = app_auth.LeproAppOAuthImplementation(self.hass)
        state = {"flow_id": "test-flow", "redirect_uri": "https://ha.invalid/callback"}
        with patch.object(
            app_auth, "async_exchange_app_token", new_callable=AsyncMock
        ) as exchange:
            await impl.async_resolve_external_data({"code": parsed, "state": state})
            exchange.assert_awaited_once_with(self.hass, APP_TOKEN)
        self.assertEqual(state["flow_id"], "test-flow")

    async def test_authorize_url_contains_registered_id_and_signed_state(self):
        impl = app_auth.LeproAppOAuthImplementation(self.hass)
        with patch.object(
            type(impl),
            "redirect_uri",
            new_callable=PropertyMock,
            return_value="https://my.home-assistant.io/redirect/oauth",
        ):
            url = await impl.async_generate_authorize_url("test-flow")
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/oauth2/app/")
        self.assertEqual(query["client_id"], [app_auth.APP_CLIENT_ID])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["user"])
        self.assertNotEqual(query["state"], ["test-flow"])
        self.assertNotIn("client_secret", query)

    async def test_unknown_region_stops_before_credentials_are_sent(self):
        session = Session([Response({"apiHost": "attacker.invalid"})])
        with self.assertRaises(client.LeproResponseError):
            await self.exchange(session)
        self.assertEqual(len(session.requests), 1)

    async def test_wrong_account_renewal_is_rejected_before_successor_request(self):
        session = Session(exchange_responses(uid="someone-else"))
        with self.assertRaises(client.LeproAuthError):
            await self.exchange(session, expected_uid="account")
        self.assertEqual(len(session.requests), 2)

    async def test_profile_identity_mismatch_is_rejected(self):
        responses = exchange_responses()
        responses[2] = Response({"uid": "someone-else"})
        session = Session(responses)
        with self.assertRaises(client.LeproAuthError):
            await self.exchange(session)
        self.assertEqual(len(session.requests), 3)

    async def test_expired_successor_is_not_stored(self):
        responses = exchange_responses()
        responses[-1] = Response({"userToken": APP_TOKEN, "tokenExpire": 1})
        with self.assertRaises(client.LeproResponseError):
            await self.exchange(Session(responses))

    async def test_incomplete_mqtt_credentials_are_not_accepted(self):
        responses = exchange_responses()
        responses[1].data.pop("secret")
        session = Session(responses)
        with self.assertRaises(client.LeproAuthError):
            await self.exchange(session)
        self.assertEqual(len(session.requests), 2)

    async def test_invalid_code_never_makes_network_request(self):
        for token in ["not base64!?!" * 2, "", None, "x" * 5000]:
            session = Session([])
            with self.assertRaises(client.LeproAuthError):
                await self.exchange(session, token)
            self.assertFalse(session.requests)

    async def test_real_ha_session_serializes_renewal_and_survives_api_recreation(self):
        entry = SimpleNamespace(
            data={
                "token": {
                    "access_token": "old",
                    "secret": "old-secret",
                    "uid": "account",
                    "refresh_token": APP_TOKEN,
                    "expires_at": 1,
                    "region": "europe",
                }
            }
        )
        updates = []

        def update(config_entry, **kwargs):
            config_entry.data = kwargs["data"]
            updates.append(kwargs["data"])

        session = Session(exchange_responses())
        with (
            patch.object(client, "async_get_clientsession", return_value=session),
            patch.object(
                self.hass.config_entries, "async_update_entry", side_effect=update
            ),
        ):
            api = app_auth.LeproAppApi(self.hass, entry)
            await asyncio.gather(
                api.async_restore_session(), api.async_restore_session()
            )
            self.assertEqual(len(updates), 1)
            self.assertEqual(api.secret, "new-mqtt-secret")
            restored = app_auth.LeproAppApi(self.hass, entry)
            await restored.async_restore_session()
            self.assertEqual(restored.token, "new-bearer")
        self.assertEqual(len(session.requests), 4)
        self.assertGreater(entry.data["token"]["expires_at"], time.time())

    async def test_real_ha_session_does_not_overwrite_on_invalid_refresh(self):
        original = {
            "access_token": "old",
            "uid": "account",
            "refresh_token": APP_TOKEN,
            "expires_at": 1,
        }
        entry = SimpleNamespace(data={"token": original})
        session = Session([Response({}, code=-900, status=401)])
        with (
            patch.object(client, "async_get_clientsession", return_value=session),
            patch.object(self.hass.config_entries, "async_update_entry") as update,
        ):
            api = app_auth.LeproAppApi(self.hass, entry)
            with self.assertRaises(client.LeproAuthError):
                await api.async_restore_session()
            update.assert_not_called()
        self.assertIs(entry.data["token"], original)

    async def test_email_and_app_choices_and_app_confirmation(self):
        flow = config_flow.LeproCloudFlow()
        flow.hass = self.hass
        result = await flow.async_step_user()
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["menu_options"], ["email", "app"])
        result = await flow.async_step_email()
        self.assertEqual(result["step_id"], "email")
        result = await flow.async_step_app()
        self.assertEqual(result["step_id"], "app")
        with patch.object(
            app_auth.LeproAppOAuthImplementation,
            "redirect_uri",
            new_callable=PropertyMock,
            return_value="https://ha.invalid/auth/external/callback",
        ):
            result = await flow.async_step_app({})
        self.assertEqual(result["type"], "external")
        self.assertEqual(result["step_id"], "auth")

    async def test_app_reauth_rejects_a_different_uid(self):
        flow = config_flow.LeproCloudFlow()
        flow.hass = self.hass
        flow.context = {"source": "reauth"}
        entry = SimpleNamespace(data={"token": {"uid": "original"}})
        with patch.object(flow, "_get_reauth_entry", return_value=entry):
            result = await flow.async_oauth_create_entry({"token": {"uid": "other"}})
        self.assertEqual(result["reason"], "wrong_account")

    async def test_app_reauth_and_reconfigure_show_app_confirmation(self):
        for source, method in [
            ("reauth", "async_step_reauth_confirm"),
            ("reconfigure", "async_step_reconfigure"),
        ]:
            flow = config_flow.LeproCloudFlow()
            flow.hass = self.hass
            entry = SimpleNamespace(data={"auth_implementation": "lepro_cloud"})
            getter = (
                "_get_reauth_entry" if source == "reauth" else "_get_reconfigure_entry"
            )
            with patch.object(flow, getter, return_value=entry):
                result = await getattr(flow, method)()
            self.assertEqual(result["step_id"], "app")

    async def test_flow_creation_persists_app_tokens_and_region_without_password(self):
        session = Session(exchange_responses())
        token = await self.exchange(session)
        flow = config_flow.LeproCloudFlow()
        flow.hass = self.hass
        flow.flow_id = "new-app-flow"
        flow.context = {"source": "user"}
        flow.external_data = {"code": APP_TOKEN}
        flow.flow_impl = SimpleNamespace(
            domain="lepro_cloud",
            async_resolve_external_data=AsyncMock(return_value=token),
        )
        result = await flow.async_step_creation()
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["region"], "europe")
        self.assertEqual(result["data"]["auth_implementation"], "lepro_cloud")
        self.assertIn("refresh_token", result["data"]["token"])
        self.assertNotIn("password", result["data"])
        self.assertGreater(result["data"]["token"]["expires_at"], time.time())

    async def test_creation_maps_rejected_callback_without_logging_credentials(self):
        flow = config_flow.LeproCloudFlow()
        flow.hass = self.hass
        flow.external_data = {"code": APP_TOKEN}
        flow.flow_impl = SimpleNamespace(
            async_resolve_external_data=AsyncMock(
                side_effect=client.LeproAuthError("Invalid app code")
            )
        )
        result = await flow.async_step_creation()
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "invalid_auth")

    async def test_rejected_code_and_throttling_have_distinct_recovery(self):
        for code, expected in [
            (-101, client.LeproAuthError),
            (-905, client.LeproApiError),
        ]:
            session = Session([Response({}, code=code, status=400)])
            with self.assertRaises(expected):
                await self.exchange(session)

    async def test_corrupt_persisted_expiry_is_rejected_without_network(self):
        entry = SimpleNamespace(
            data={"token": {"uid": "account", "expires_at": float("inf")}}
        )
        session = Session([])
        with patch.object(client, "async_get_clientsession", return_value=session):
            api = app_auth.LeproAppApi(self.hass, entry)
            with self.assertRaises(client.LeproAuthError):
                await api.async_restore_session()
        self.assertFalse(session.requests)

    async def test_cancelled_renewal_does_not_overwrite_stored_credentials(self):
        entry = SimpleNamespace(
            data={
                "token": {
                    "uid": "account",
                    "access_token": "old",
                    "refresh_token": APP_TOKEN,
                    "expires_at": 1,
                }
            }
        )
        original = entry.data["token"]
        session = Session([])
        session.request = AsyncMock(side_effect=asyncio.CancelledError)
        with (
            patch.object(client, "async_get_clientsession", return_value=session),
            patch.object(self.hass.config_entries, "async_update_entry") as update,
        ):
            api = app_auth.LeproAppApi(self.hass, entry)
            with self.assertRaises(asyncio.CancelledError):
                await api.async_restore_session()
            update.assert_not_called()
        self.assertIs(entry.data["token"], original)

    async def test_mqtt_reconnects_once_when_renewal_changes_only_secret(self):
        api = SimpleNamespace(
            token="new",
            secret="new-secret",
            uid="account",
            async_profile=AsyncMock(return_value={}),
            async_devices=AsyncMock(return_value=[]),
        )
        co = client.LeproCoordinator(
            self.hass, SimpleNamespace(data={"region": "europe"}), api=api
        )
        info = {"host": "broker.invalid", "port": 8883}
        certs = {"ca": "same-ca", "cert": "same-cert", "key": "same-key"}
        co.connected = True
        co._profile_signature = co._signature(info, certs)
        co._mqtt_secret = "old-secret"
        co._load_product_configs = AsyncMock(return_value=False)
        co._load_device_scenes = AsyncMock()
        co._resolve_certs = AsyncMock(return_value=certs)
        co._stop_transport = AsyncMock()
        co._async_start_mqtt = AsyncMock()
        co._notify_all = Mock()
        with (
            patch.object(client, "_mqtt_info", return_value=info),
            patch.object(client, "load_mqtt_private_key", return_value="unused"),
        ):
            await co._refresh_session()
            await co._refresh_session()
        co._stop_transport.assert_awaited_once()
        co._async_start_mqtt.assert_awaited_once()
        self.assertEqual(co._mqtt_secret, "new-secret")

    async def test_renewed_credentials_are_saved_by_real_ha_storage(self):
        kwargs = {
            "domain": "lepro_cloud",
            "title": "App auth test",
            "data": {
                "auth_implementation": "lepro_cloud",
                "region": "europe",
                "token": {
                    "access_token": "old",
                    "secret": "old-secret",
                    "uid": "account",
                    "refresh_token": APP_TOKEN,
                    "expires_at": 1,
                    "region": "europe",
                },
            },
            "options": {},
            "source": "user",
            "unique_id": "app:account",
            "version": 1,
            "minor_version": 1,
            "discovery_keys": {},
            "subentries_data": [],
            "disabled_by": ConfigEntryDisabler.USER,
        }
        entry = ConfigEntry(
            **{
                k: v
                for k, v in kwargs.items()
                if k in inspect.signature(ConfigEntry).parameters
            }
        )
        await self.hass.config_entries.async_add(entry)
        session = Session(exchange_responses())
        with patch.object(client, "async_get_clientsession", return_value=session):
            api = app_auth.LeproAppApi(self.hass, entry)
            await api.async_restore_session()
        # This minimal test HA was never started, so force the pending storage
        # write through HA's real Store rather than relying on shutdown events.
        await self.hass.config_entries._store.async_save(
            self.hass.config_entries._data_to_save()
        )
        saved = json.loads(
            Path(self.hass.config.path(".storage/core.config_entries")).read_text()
        )
        stored = next(
            e for e in saved["data"]["entries"] if e["entry_id"] == entry.entry_id
        )
        self.assertEqual(stored["data"]["token"]["access_token"], "new-bearer")
        self.assertEqual(stored["data"]["token"]["secret"], "new-mqtt-secret")
        self.assertGreater(stored["data"]["token"]["expires_at"], time.time())
        restarted = HomeAssistant(self.hass.config.config_dir)
        loader.async_setup(restarted)
        restarted.config_entries = ConfigEntries(restarted, {})
        try:
            await restarted.config_entries.async_initialize()
            restored_entry = restarted.config_entries.async_get_entry(entry.entry_id)
            self.assertIsNotNone(restored_entry)
            no_requests = Session([])
            with patch.object(
                client, "async_get_clientsession", return_value=no_requests
            ):
                restored_api = app_auth.LeproAppApi(restarted, restored_entry)
                await restored_api.async_restore_session()
            self.assertEqual(restored_api.token, "new-bearer")
            self.assertEqual(restored_api.secret, "new-mqtt-secret")
            self.assertFalse(no_requests.requests)
        finally:
            await restarted.async_stop()

    async def test_app_start_restores_credentials_before_discovery_without_password(
        self,
    ):
        order = []
        api = SimpleNamespace(token=None, secret=None, uid=None)

        async def restore():
            order.append("restore")
            api.token, api.secret, api.uid = "restored", "restored-secret", "account"

        async def profile():
            order.append("profile")
            return {}

        api.async_restore_session = AsyncMock(side_effect=restore)
        api.async_profile = AsyncMock(side_effect=profile)
        api.async_devices = AsyncMock(return_value=[])
        entry = SimpleNamespace(
            data={"auth_implementation": "lepro_cloud", "region": "europe"}
        )
        co = client.LeproCoordinator(self.hass, entry, api=api)
        co._load_product_configs = AsyncMock(return_value=False)
        co._load_device_scenes = AsyncMock()
        co._resolve_certs = AsyncMock(
            return_value={"ca": "ca", "cert": "cert", "key": "key"}
        )
        co._async_start_mqtt = AsyncMock()
        try:
            with (
                patch.object(
                    client,
                    "_mqtt_info",
                    return_value={"host": "broker.invalid", "port": 8883},
                ),
                patch.object(client, "load_mqtt_private_key", return_value="unused"),
            ):
                await co.async_start()
            self.assertEqual(order, ["restore", "profile"])
            self.assertEqual(co._mqtt_secret, "restored-secret")
        finally:
            await co.async_stop()

    async def test_network_failure_keeps_session_and_later_renewal_recovers(self):
        entry = SimpleNamespace(
            data={
                "token": {
                    "uid": "account",
                    "access_token": "old",
                    "refresh_token": APP_TOKEN,
                    "expires_at": 1,
                }
            }
        )
        original = entry.data["token"]
        session = Session(exchange_responses())
        request = session.request
        first = True

        async def interrupted_request(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                raise OSError("offline")
            return await request(*args, **kwargs)

        session.request = interrupted_request
        updates = []

        def update(config_entry, **kwargs):
            config_entry.data = kwargs["data"]
            updates.append(kwargs["data"])

        with (
            patch.object(client, "async_get_clientsession", return_value=session),
            patch.object(
                self.hass.config_entries, "async_update_entry", side_effect=update
            ),
        ):
            api = app_auth.LeproAppApi(self.hass, entry)
            with self.assertRaises(client.LeproApiError):
                await api.async_restore_session()
            self.assertIs(entry.data["token"], original)
            self.assertFalse(updates)
            await api.async_restore_session()
        self.assertEqual(api.token, "new-bearer")
        self.assertEqual(len(updates), 1)

    async def test_app_api_preserves_validated_account_host_migration(self):
        entry = SimpleNamespace(
            data={
                "token": {
                    "uid": "account",
                    "access_token": "token",
                    "secret": "secret",
                    "expires_at": time.time() + 3600,
                    "region": "europe",
                }
            }
        )
        session = Session(
            [
                Response({"apiHost": "api-na-iot.lepro.com"}, code=-100),
                Response({"uid": "account"}),
                Response({"uid": "account"}),
            ]
        )
        with patch.object(client, "async_get_clientsession", return_value=session):
            api = app_auth.LeproAppApi(self.hass, entry)
            await api.async_profile()
            await api.async_profile()
        self.assertIn("api-eu-iot.lepro.com", session.requests[0][1])
        self.assertIn("api-na-iot.lepro.com", session.requests[1][1])
        self.assertIn("api-na-iot.lepro.com", session.requests[2][1])

    async def test_email_flow_does_not_duplicate_an_app_authorized_account(self):
        flow = config_flow.LeproCloudFlow()
        flow.hass = self.hass
        flow.context = {"source": "user"}
        api = SimpleNamespace(uid="account", async_login=AsyncMock())
        with (
            patch.object(config_flow, "LeproApi", return_value=api),
            patch.object(
                config_flow,
                "_async_account_region",
                new_callable=AsyncMock,
                return_value="europe",
            ),
            patch.object(
                self.hass.config_entries,
                "async_entry_for_domain_unique_id",
                return_value=object(),
            ),
        ):
            result = await flow.async_step_email(
                {"username": "person@example.invalid", "password": "unused"}
            )
        self.assertEqual(result["reason"], "already_configured")

    async def test_app_flow_does_not_duplicate_a_legacy_email_account(self):
        flow = config_flow.LeproCloudFlow()
        flow.hass = self.hass
        flow.context = {"source": "user"}
        token = {
            "uid": "account",
            "region": "europe",
            "account": "person@example.invalid",
        }
        with (
            patch.object(
                flow, "async_set_unique_id", new_callable=AsyncMock, return_value=None
            ),
            patch.object(
                self.hass.config_entries,
                "async_entry_for_domain_unique_id",
                return_value=object(),
            ),
        ):
            result = await flow.async_oauth_create_entry({"token": token})
        self.assertEqual(result["reason"], "already_configured")


if __name__ == "__main__":
    unittest.main(verbosity=2)
