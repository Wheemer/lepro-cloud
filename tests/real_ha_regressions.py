"""Offline regression tests using actual Home Assistant classes, not import stubs.

Run with the checkout at /source and writable test storage at /audit.
APK references: RemoteErrorCode; SceneEntityKt; Dp6Scene; DeviceExtKt;
MqttConnection.dealDpValue/dealSetResponse; PlugMainPage AOT writers.
"""

import asyncio
import inspect
import json
import sys
import time
import unittest
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, "/source")
# Initialize HA core before its loader.
from homeassistant.core import HomeAssistant

# isort: split

from homeassistant import loader
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.helpers import area_registry, device_registry, entity_registry
from homeassistant.setup import async_setup_component

from custom_components.lepro_cloud import client, diagnostics, light, switch
from custom_components.lepro_cloud.catalog import BULB_PRESETS, PRODUCT_CONFIGS
from custom_components.lepro_cloud.device import is_supported_device
from custom_components.lepro_cloud.protocol import (
    ha_to_lepro_brightness,
    scene_brightness,
)
from custom_components.lepro_cloud.scenes import merge_scenes, selected_effect

RUN_ID = str(time.time_ns())


class Broker:
    def __init__(self):
        self.messages = []
        self.subscriptions = []
        self.stopped = []

    def publish(self, topic, payload, qos=0):
        self.messages.append((topic, json.loads(payload)))
        return SimpleNamespace(rc=0)

    def subscribe(self, topic, qos=0):
        self.subscriptions.append(topic)
        return (0, len(self.subscriptions))

    def disconnect(self):
        self.stopped.append("disconnect")

    def loop_stop(self):
        self.stopped.append("loop_stop")


class OfflineRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        root = Path("/audit/config-regressions") / RUN_ID / self._testMethodName
        root.mkdir(parents=True, exist_ok=True)
        self.hass = HomeAssistant(str(root))
        self.entry = SimpleNamespace(
            entry_id="audit",
            unique_id="europe:audit@example.invalid",
            data={
                "region": "europe",
                "username": "audit@example.invalid",
                "password": "unused",
            },
            async_start_reauth=lambda hass: self.reauth.append(True),
        )
        self.reauth = []
        self.session_patch = patch.object(
            client, "async_get_clientsession", return_value=None
        )
        self.session_patch.start()
        self.co = client.LeproCoordinator(self.hass, self.entry)
        self.co.devices = {
            "lamp": {"type": 1, "did": "lamp", "series": "TB1"},
            "plug": {"type": 2, "did": "plug", "series": "P1"},
        }
        self.broker = Broker()
        self.co.client = self.broker
        self.co.connected = True

    async def asyncTearDown(self):
        await self.co.async_stop()
        await self.hass.async_stop()
        self.session_patch.stop()

    async def report(self, did, data, suffix="rpt", **extra):
        self.co._on_message(
            self.broker,
            None,
            SimpleNamespace(
                topic=f"le/{did}/prp/{suffix}",
                payload=json.dumps({"d": data, **extra}).encode(),
            ),
        )
        await asyncio.sleep(0)

    async def test_full_startup_and_stop_with_existing_session(self):
        profile = {
            "mqtt": {"host": "broker", "port": 8883, "root": "root", "cert": "cert"}
        }
        self.co.api = SimpleNamespace(
            token="fixture",
            secret="fixture",
            async_login=AsyncMock(),
            async_profile=AsyncMock(return_value=profile),
            async_devices=AsyncMock(return_value=list(self.co.devices.values())),
            async_product_configs=AsyncMock(side_effect=client.LeproApiError()),
            async_device_scenes=AsyncMock(return_value=[]),
        )
        self.co._resolve_certs = AsyncMock(
            return_value={"root": "root", "cert": "cert", "key": "key"}
        )
        self.co._async_start_mqtt = AsyncMock()
        with patch.object(client, "load_mqtt_private_key", return_value="key"):
            await self.co.async_start()
        self.co.api.async_login.assert_not_called()
        self.assertIsNotNone(self.co._maintenance_task)
        self.assertTrue(self.co.effect_types)
        await self.co.async_stop()
        self.assertIsNone(self.co._maintenance_task)

    async def test_saved_scene_refresh_handles_edits_deletions_and_service_outage(self):
        self.co.devices = {
            "lamp": {"did": "lamp", "scenes": [{"cid": 1, "name": "Embedded"}]}
        }
        self.co.api = SimpleNamespace(
            async_device_scenes=AsyncMock(
                side_effect=[
                    [{"cid": 2, "name": "Old"}],
                    [],
                    [{"cid": 2, "name": "Edited"}],
                    [],
                    [],
                ]
            )
        )
        await self.co._load_device_scenes()
        self.assertEqual(
            [s["name"] for s in self.co.devices["lamp"]["scenes"]], ["Embedded", "Old"]
        )
        self.co.devices["lamp"]["scenes"] = [{"cid": 1, "name": "Embedded"}]
        await self.co._load_device_scenes()
        self.assertEqual(
            [s["name"] for s in self.co.devices["lamp"]["scenes"]],
            ["Embedded", "Edited"],
        )
        self.co.devices["lamp"]["scenes"] = []
        await self.co._load_device_scenes()
        self.assertEqual(self.co.devices["lamp"]["scenes"], [])
        self.co.api.async_device_scenes = AsyncMock(side_effect=client.LeproApiError())
        await self.co._load_device_scenes()
        self.assertEqual(self.co.devices["lamp"]["scenes"], [])

    async def test_real_flow_update_helpers_accept_minimum_ha_api(self):
        from custom_components.lepro_cloud import config_flow

        for step in ("reconfigure", "reauth_confirm"):
            entry = SimpleNamespace(
                entry_id="flow-entry",
                data={
                    "username": "audit@example.invalid",
                    "password": "old",
                    "region": "europe",
                },
                unique_id="europe:audit@example.invalid",
                update_listeners=[],
            )
            reloads = []

            def update(entry, **kwargs):
                entry.data = kwargs["data"]
                entry.unique_id = kwargs["unique_id"]
                return True

            entries = SimpleNamespace(
                async_update_entry=update,
                async_schedule_reload=reloads.append,
                async_get_entry=lambda key, saved=entry: saved,
                flow=SimpleNamespace(
                    async_progress_by_handler=lambda *args, **kwargs: []
                ),
            )
            flow = config_flow.LeproCloudFlow()
            flow.hass = SimpleNamespace(data={}, config_entries=entries)
            flow.context = {
                "entry_id": entry.entry_id,
                "source": "reauth" if step == "reauth_confirm" else "reconfigure",
            }
            api = SimpleNamespace(async_login=AsyncMock())
            with (
                patch.object(flow, "_get_reauth_entry", return_value=entry),
                patch.object(flow, "_get_reconfigure_entry", return_value=entry),
                patch.object(
                    flow,
                    "async_set_unique_id",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch.object(
                    config_flow,
                    "_async_account_region",
                    new_callable=AsyncMock,
                    return_value="europe",
                ),
                patch.object(config_flow, "LeproApi", return_value=api),
            ):
                result = await getattr(flow, "async_step_" + step)(
                    {"username": "audit@example.invalid", "password": "new"}
                )
            self.assertEqual(
                result["reason"],
                "reauth_successful"
                if step == "reauth_confirm"
                else "reconfigure_successful",
            )
            self.assertEqual(entry.data["password"], "new")
            self.assertEqual(reloads, ["flow-entry"])

    async def test_reauth_rejects_another_account_before_login(self):
        from custom_components.lepro_cloud.config_flow import LeproCloudFlow

        flow = LeproCloudFlow()
        flow.hass = self.hass
        with patch.object(flow, "_get_reauth_entry", return_value=self.entry):
            result = await flow.async_step_reauth_confirm(
                {"username": "someone-else@example.invalid", "password": "unused"}
            )
        self.assertEqual(result["errors"], {"base": "wrong_account"})

    async def test_failed_maintenance_task_cannot_skip_transport_cleanup(self):
        async def fail():
            raise RuntimeError("fixture")

        self.co._maintenance_task = asyncio.create_task(fail())
        await asyncio.sleep(0)
        with self.assertRaises(RuntimeError):
            await self.co.async_stop()
        self.assertIsNone(self.co.client)
        self.assertEqual(self.broker.stopped, ["disconnect", "loop_stop"])

    async def test_cancelled_mqtt_start_collects_worker_before_cleanup(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def executor(fn, *args):
            started.set()
            await release.wait()

        # Patch only this isolated executor await; actual MQTT is never started.
        with (
            patch.object(self.hass, "async_add_executor_job", side_effect=executor),
            patch.object(self.co, "_stop_transport", new_callable=AsyncMock) as stop,
        ):
            task = asyncio.create_task(self.co._async_start_mqtt({}, {}))
            await started.wait()
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            stop.assert_awaited_once()

    async def test_real_paho_mutual_tls_query_command_reconnect_and_shutdown(self):
        import ssl

        root = Path(self.hass.config.path("tls-fixture"))
        root.mkdir()
        key = root / "fixture-key.pem"
        cert = root / "fixture-cert.pem"

        def generate():
            import datetime
            import ipaddress

            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509.oid import NameOID

            private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
            now = datetime.datetime.now(datetime.UTC)
            certificate = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(subject)
                .public_key(private.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=2))
                .add_extension(
                    x509.BasicConstraints(ca=True, path_length=None), critical=True
                )
                .add_extension(
                    x509.SubjectAlternativeName(
                        [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
                    ),
                    critical=False,
                )
                .sign(private, hashes.SHA256())
            )
            key.write_bytes(
                private.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

        await asyncio.to_thread(generate)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        context.load_verify_locations(cafile=str(cert))
        context.verify_mode = ssl.CERT_REQUIRED
        packets = []
        connections = []
        tasks = set()

        def frame(topic, data):
            topic = topic.encode()
            body = len(topic).to_bytes(2, "big") + topic + json.dumps(data).encode()
            length = len(body)
            encoded = []
            while True:
                digit = length % 128
                length //= 128
                encoded.append(digit | (128 if length else 0))
                if not length:
                    break
            return bytes([0x30, *encoded]) + body

        async def broker(reader, writer):
            tasks.add(asyncio.current_task())
            connections.append(writer)
            try:
                while True:
                    header = (await reader.readexactly(1))[0]
                    size = 0
                    multiplier = 1
                    while True:
                        digit = (await reader.readexactly(1))[0]
                        size += (digit & 127) * multiplier
                        if not digit & 128:
                            break
                        multiplier *= 128
                    body = await reader.readexactly(size)
                    kind = header >> 4
                    if kind == 1:
                        writer.write(b"\x20\x02\x00\x00")
                    elif kind == 8:
                        writer.write(b"\x90\x03" + body[:2] + b"\x00")
                    elif kind == 12:
                        writer.write(b"\xd0\x00")
                    elif kind == 3:
                        length = int.from_bytes(body[:2], "big")
                        topic = body[2 : 2 + length].decode()
                        data = json.loads(body[2 + length :])
                        packets.append((topic, data))
                        if topic.endswith("/get"):
                            writer.write(
                                frame(
                                    topic + "r",
                                    {
                                        "id": data["id"],
                                        "d": {"d1": 1, "d2": 0, "d3": 500},
                                    },
                                )
                            )
                        elif topic.endswith("/set"):
                            writer.write(
                                frame(
                                    topic + "r",
                                    {"id": data["id"], "c": 0, "d": data["d"]},
                                )
                            )
                    elif kind == 14:
                        return
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()
                tasks.discard(asyncio.current_task())

        server = await asyncio.start_server(broker, "127.0.0.1", 0, ssl=context)

        async def until(predicate):
            async with asyncio.timeout(15):
                while not predicate():
                    await asyncio.sleep(0.02)

        await self.co._stop_transport()
        self.co.devices = {"123": {"did": "123", "type": 1, "series": "B1"}}
        self.co.api.secret = "fixture-secret"
        try:
            await self.co._async_start_mqtt(
                {"host": "127.0.0.1", "port": server.sockets[0].getsockname()[1]},
                {
                    "root": cert.read_text(),
                    "cert": cert.read_text(),
                    "key": key.read_text(),
                    "key_password": "fixture",
                },
            )
            await until(lambda: self.co.device_available("123"))
            self.assertTrue(packets)
            self.assertTrue(all(topic.endswith("/get") for topic, _ in packets))
            await self.hass.async_add_executor_job(self.co.command, "123", {"d1": 0})
            await until(lambda: self.co.states["123"].get("d1") == 0)
            self.assertFalse(self.co._pending_commands)
            connections[0].close()
            await until(lambda: not self.co.connected)
            await until(
                lambda: len(connections) > 1 and self.co.device_available("123")
            )
            await self.co.async_stop()
            self.assertIsNone(self.co.client)
            self.assertIsNone(self.co.tmp)
        finally:
            await self.co.async_stop()
            server.close()
            await server.wait_closed()
            for writer in connections:
                writer.close()
            for task in list(tasks):
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_low_tv_brightness_and_white_readback_use_the_correct_fields(self):
        entity = light.LeproCloudLight(self.co, "lamp", {"type": 1, "series": "STV1"})
        entity.hass = self.hass
        self.co.states["lamp"] = {"d2": 5, "d52": 500}
        await entity.async_turn_on(brightness=1)
        self.assertEqual(self.broker.messages[-1][1]["d"], {"d1": 1, "d2": 5, "d52": 4})
        self.co.states["lamp"] = {"d2": 0, "d3": 1000, "d52": 500}
        self.assertEqual(entity.brightness, 255)

    async def test_d6_dimming_uses_the_scene_even_when_d52_is_cached(self):
        value = BULB_PRESETS["Gradient"]
        self.co.states["lamp"] = {"d2": 2, "d6": value, "d52": 500}
        entity = light.LeproCloudLight(self.co, "lamp", {"type": 1, "series": "B1"})
        entity.hass = self.hass
        self.assertEqual(entity.brightness, 255)
        await entity.async_turn_on(brightness=128)
        self.assertEqual(
            self.broker.messages[-1][1]["d"],
            {"d1": 1, "d2": 2, "d6": scene_brightness(value, 502)},
        )
        await self.report("lamp", {"d6": scene_brightness(value, 502)})
        self.assertEqual(entity.brightness, 128)
        self.assertEqual(entity.effect, "Gradient")

    async def test_saved_brightness_metadata_is_used_unless_ha_overrides_it(self):
        device = {
            "type": 1,
            "series": "TB1",
            "effect": "earthlight",
            "scenes": [
                {
                    "name": "Favorite",
                    "earthlight": {
                        "dp": "d50",
                        "res": "multipart;unchanged",
                        "scene": "brightness=345&speed=50",
                    },
                }
            ],
        }
        entity = light.LeproCloudLight(self.co, "lamp", device)
        entity.hass = self.hass
        await entity.async_turn_on(effect="Favorite")
        self.assertEqual(self.broker.messages[-1][1]["d"]["d52"], 345)
        self.assertEqual(self.broker.messages[-1][1]["d"]["d50"], "multipart;unchanged")
        await entity.async_turn_on(effect="Favorite", brightness=255)
        self.assertEqual(self.broker.messages[-1][1]["d"]["d52"], 1000)

    async def test_reconfigure_api_cache_cannot_be_overwritten_by_old_unload(self):
        fresh = SimpleNamespace(token="new")
        old = SimpleNamespace(token="old")
        client.cache_authenticated_api(self.hass, "account", fresh)
        client.cache_authenticated_api(self.hass, "account", old, replace=False)
        self.assertIs(client.take_authenticated_api(self.hass, "account"), fresh)
        self.assertIsNone(client.take_authenticated_api(self.hass, "account"))

    async def test_broker_subscription_rejection_and_publish_exception_are_visible(
        self,
    ):
        self.co._on_subscribe(self.broker, None, 1, [128], None)
        self.assertFalse(self.co.connected)
        self.co.connected = True
        self.broker.publish = lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("fixture")
        )
        with self.assertRaises(client.LeproMqttError):
            await self.hass.async_add_executor_job(self.co.command, "lamp", {"d1": 1})
        self.assertFalse(self.co._pending_commands)

    async def test_packaged_icon_decodes_and_failed_unload_keeps_transport(self):
        from PIL import Image

        from custom_components import lepro_cloud

        icon = Path(light.__file__).parent / "brand/icon.png"

        def verify_image():
            with Image.open(icon) as image:
                image.load()
                return image.size

        width, height = await asyncio.to_thread(verify_image)
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)
        self.entry.runtime_data = self.co
        original = self.hass.config_entries
        self.hass.config_entries = SimpleNamespace(
            async_unload_platforms=AsyncMock(return_value=False)
        )
        try:
            self.assertFalse(
                await lepro_cloud.async_unload_entry(self.hass, self.entry)
            )
            self.assertTrue(self.co.connected)
            self.assertIs(self.co.client, self.broker)
        finally:
            self.hass.config_entries = original

    async def test_installation_identity_is_stable_across_accounts(self):
        from homeassistant.helpers import instance_id

        api = client.LeproApi(self.hass, "europe")
        api._request = AsyncMock(
            return_value={"token": "token", "uid": "uid", "secret": "secret"}
        )
        with patch.object(
            instance_id,
            "async_get",
            new_callable=AsyncMock,
            return_value="ha-instance-1",
        ):
            await api.async_login("one@example.invalid", "password")
            first = api._request.call_args.args[2]["mac"]
            await api.async_login("two@example.invalid", "password")
            self.assertEqual(api._request.call_args.args[2]["mac"], first)
        with patch.object(
            instance_id,
            "async_get",
            new_callable=AsyncMock,
            return_value="ha-instance-2",
        ):
            await api.async_login("one@example.invalid", "password")
            self.assertNotEqual(api._request.call_args.args[2]["mac"], first)

    async def test_rotating_certificate_urls_do_not_restart_an_unchanged_connection(
        self,
    ):
        certs = {
            "root": "root PEM",
            "cert": "cert PEM",
            "key": "key PEM",
            "key_password": "fixture",
        }
        first = {"host": "broker", "port": 8883, "root": "url-1", "cert": "url-2"}
        second = {"host": "broker", "port": "8883", "root": "url-3", "cert": "url-4"}
        self.assertEqual(
            self.co._signature(first, certs), self.co._signature(second, certs)
        )

    async def test_apk_negative_auth_codes_and_non_auth_failures(self):
        for code in (-202, -203, -204, -205, -900, -904, -905, -100):
            api = client.LeproApi.__new__(client.LeproApi)
            api._host = "invalid"
            api.token = None
            response = SimpleNamespace(
                status=400,
                json=AsyncMock(
                    return_value={"code": code, "data": {}, "msg": "fixture"}
                ),
            )
            api._session = SimpleNamespace(request=AsyncMock(return_value=response))
            expected = (
                client.LeproAuthError
                if code in (-202, -203, -204, -205, -900)
                else client.LeproResponseError
            )
            with self.subTest(code=code), self.assertRaises(expected):
                await api._request("POST", "/user/login", {})

    async def test_region_migration_is_bounded_and_allowlisted(self):
        api = client.LeproApi.__new__(client.LeproApi)
        api._host = "old.invalid"
        api.token = None

        def response(data):
            return SimpleNamespace(status=200, json=AsyncMock(return_value=data))

        api._session = SimpleNamespace(
            request=AsyncMock(
                side_effect=[
                    response(
                        {"code": -100, "data": {"apiHost": "api-eu-iot.lepro.com"}}
                    ),
                    response({"code": 0, "data": {"ok": True}}),
                ]
            )
        )
        self.assertEqual(await api._request("GET", "/user/profile"), {"ok": True})
        self.assertEqual(api._host, "api-eu-iot.lepro.com")
        self.assertEqual(api._session.request.await_count, 2)

    async def test_shared_and_owned_discovery_keeps_owner_family_and_favorites(self):
        api = client.LeproApi.__new__(client.LeproApi)
        api._request = AsyncMock(
            side_effect=[
                {"list": [{"fid": "receiving"}, {"fid": "owned"}]},
                {
                    "list": [
                        {
                            "did": "shared",
                            "fid": "owner",
                            "deviceSource": 1,
                            "scenes": [{"cid": 1, "name": "Favorite"}],
                        }
                    ]
                },
                {"list": [{"did": "owned", "scenes": []}]},
            ]
        )
        devices = await api.async_devices()
        self.assertEqual(devices[0]["fid"], "owner")
        self.assertEqual(devices[0]["scenes"][0]["name"], "Favorite")
        self.assertEqual(devices[1]["fid"], "owned")
        self.assertEqual(api._request.await_count, 3)

    async def test_family_and_scene_sources_reconcile_by_identity(self):
        self.assertEqual(
            merge_scenes(
                [{"cid": 1, "name": "Old"}, {"cid": 2, "name": "Embedded"}],
                [{"cid": 1, "name": "Edited"}],
            ),
            [{"cid": 1, "name": "Edited"}, {"cid": 2, "name": "Embedded"}],
        )
        scene = {
            "smartbulb": {"dp": "d6", "res": BULB_PRESETS["Gradient"]},
            "floorlight": {"dp": "d50", "res": "wrong"},
            "neonlight": {"dp": "d50", "res": "right"},
        }
        self.assertEqual(selected_effect(scene, "smartbulb")[0], "d6")
        self.assertEqual(selected_effect(scene, "striplight"), ("d50", "right"))
        self.assertIsNone(selected_effect(scene, "earthlight"))
        self.assertIsNone(selected_effect(scene, "unknown"))

    async def test_scene_pagination_exceeds_old_hundred_page_cap(self):
        async def page(device, cursor=0):
            return [{"cid": cursor + 1}] if cursor < 102 else []

        self.co.api = SimpleNamespace(async_device_scenes=page)
        scenes = await self.co._async_device_scenes({"did": "lamp", "fid": "owner"})
        self.assertEqual(len(scenes), 102)

    async def test_partial_reports_and_explicit_offline_precedence(self):
        for data in (
            {"d1": 1},
            {"d102": 1},
            {"d2": 0, "d3": 500},
            {"d50": "pattern"},
            {"d52": 500},
        ):
            with self.subTest(data=data):
                self.co.states.clear()
                await self.report("lamp", data)
                self.assertEqual(self.co.states["lamp"]["online"], 1)
        await self.report("lamp", {"online": 0, "d52": 500})
        self.assertFalse(self.co.device_available("lamp"))
        await self.report("lamp", {"online": [], "d1": 1})
        self.assertFalse(self.co.device_available("lamp"))
        self.assertFalse(any(t.endswith("/set") for t, _ in self.broker.messages))

    async def test_reconnect_requires_fresh_device_state(self):
        await self.report("lamp", {"online": 1, "d1": 1})
        self.assertTrue(self.co.device_available("lamp"))
        self.co._on_connect(self.broker, None, None, 0, None)
        await asyncio.sleep(0)
        self.assertFalse(self.co.device_available("lamp"))
        await self.report("lamp", {"d1": 1})
        self.assertTrue(self.co.device_available("lamp"))

    async def test_eleven_devices_subscribe_and_only_get_on_startup(self):
        self.co.devices = {
            str(i): {"did": str(i), "type": 1, "series": "B1"} for i in range(11)
        }
        self.co.api.secret = "fixture-secret"
        self.co._on_connect(self.broker, None, None, 0, None)
        await asyncio.sleep(0)
        self.assertEqual(len(self.broker.messages), 11)
        self.assertEqual(len(self.broker.subscriptions), 45)
        self.assertIn("le/fixture-secret/act/app/exe", self.broker.subscriptions)
        self.assertTrue(all(t.endswith("/get") for t, _ in self.broker.messages))

    async def test_command_queue_acceptance_does_not_fabricate_state(self):
        await self.hass.async_add_executor_job(self.co.command, "plug", {"d1": 1})
        await asyncio.sleep(0)
        self.assertNotIn("plug", self.co.states)
        identifier = self.broker.messages[-1][1]["id"]
        await self.report("lamp", {}, suffix="setr", id=identifier, c=0)
        self.assertIn(identifier, self.co._pending_commands)
        await self.report("plug", {}, suffix="setr", id=identifier, c=1)
        self.assertNotIn(identifier, self.co._pending_commands)
        self.assertNotIn("plug", self.co.states)
        self.assertEqual(self.broker.messages[-1][0], "le/plug/prp/get")
        await self.report("plug", {"d1": 1})
        self.assertEqual(self.co.states["plug"]["d1"], 1)

    async def test_command_timeout_only_queries_and_cleanup_cancels_timers(self):
        await self.hass.async_add_executor_job(self.co.command, "plug", {"d1": 0})
        await asyncio.sleep(0)
        identifier = self.broker.messages[-1][1]["id"]
        self.co._expire_command(identifier)
        self.assertEqual(self.broker.messages[-1][0], "le/plug/prp/get")
        self.assertTrue(self.co._command_timers)
        await self.co.async_stop()
        self.assertFalse(self.co._command_timers)
        self.assertFalse(self.co._pending_commands)

    async def test_account_action_requires_matching_secret_and_logout_reauths_once(
        self,
    ):
        self.co.api.secret = "fixture-secret"
        for secret in ("wrong", "fixture-secret", "fixture-secret"):
            self.co._on_message(
                self.broker,
                None,
                SimpleNamespace(
                    topic=f"le/{secret}/act/app/exe",
                    payload=b'{"d":{"action":"logout"}}',
                ),
            )
            await self.hass.async_block_till_done()
        self.assertEqual(self.reauth, [True])
        self.assertFalse(self.co.connected)
        self.assertEqual(self.broker.stopped, ["disconnect", "loop_stop"])

    async def test_recovery_never_relogs_in_on_revoked_credentials(self):
        self.co.api = SimpleNamespace(
            async_profile=AsyncMock(side_effect=client.LeproAuthError()),
            async_login=AsyncMock(),
        )
        with self.assertRaises(client.LeproAuthError):
            await self.co._refresh_session()
        self.co.api.async_login.assert_not_called()
        await self.co._require_reauth()
        self.assertEqual(self.reauth, [True])

    async def test_changed_certificate_content_restarts_even_with_same_profile_urls(
        self,
    ):
        profile = {
            "mqtt": {
                "host": "broker",
                "port": 8883,
                "root": "same-root",
                "cert": "same-cert",
            }
        }
        self.co.api = SimpleNamespace(
            async_profile=AsyncMock(return_value=profile),
            async_devices=AsyncMock(return_value=list(self.co.devices.values())),
            secret="fixture",
        )
        self.co._load_device_scenes = AsyncMock()
        self.co._resolve_certs = AsyncMock(
            return_value={"root": "new", "cert": "new", "key": "key"}
        )
        self.co._async_start_mqtt = AsyncMock()
        with patch.object(client, "load_mqtt_private_key", return_value="key"):
            await self.co._refresh_session()
        self.co._async_start_mqtt.assert_awaited_once()
        self.assertEqual(self.broker.stopped, ["disconnect", "loop_stop"])

    async def test_stop_finishes_cleanup_when_disconnect_fails(self):
        self.broker.disconnect = lambda: (_ for _ in ()).throw(OSError("fixture"))
        cleanup = SimpleNamespace(cleanup=lambda: self.broker.stopped.append("cleanup"))
        self.co.tmp = cleanup
        await self.co.async_stop()
        self.assertEqual(self.broker.stopped, ["loop_stop", "cleanup"])
        self.assertIsNone(self.co.client)
        self.assertIsNone(self.co.tmp)

    async def test_d6_white_and_color_units_preserve_timing_and_other_fields(self):
        header = "0100320064"
        color = "01" + "0078" + "03E8" + "03E8" + "0000" + "0000"
        white = "02" + "0000" + "0000" + "0000" + "03E8" + "01F4"
        rewritten = scene_brightness(header + color + white, 500)
        self.assertEqual(
            rewritten, header + "01007803E801F400000000" + "0200000000000001F401F4"
        )
        with self.assertRaises(ValueError):
            scene_brightness("0001", 500)

    async def test_apk_brightness_ranges_and_firmware_compensation(self):
        self.assertEqual(ha_to_lepro_brightness(0), 10)
        self.assertEqual(ha_to_lepro_brightness(0, effect=True), 100)
        self.assertEqual(
            ha_to_lepro_brightness(255, series="S1-10", firmware="2.0.16"), 890
        )
        self.assertEqual(
            ha_to_lepro_brightness(255, series="S1-10", firmware="2.0.17"), 1000
        )

    async def test_brightness_preserves_all_work_modes_with_cached_color(self):
        for mode, dp in ((0, "d3"), (1, "d5"), (2, "d52"), (3, "d52"), (5, "d52")):
            self.co.states["lamp"] = {
                "d1": 1,
                "d2": mode,
                "d3": 500,
                "d4": 500,
                "d5": "007803E801F4",
                "d52": 500,
            }
            entity = light.LeproCloudLight(
                self.co, "lamp", {"type": 1, "series": "STV1"}
            )
            entity.hass = self.hass
            await entity.async_turn_on(brightness=128)
            values = self.broker.messages[-1][1]["d"]
            with self.subTest(mode=mode):
                self.assertEqual(values["d2"], mode)
                self.assertIn(dp, values)
                self.assertEqual(self.co.states["lamp"]["d2"], mode)

    async def test_p1_writer_values_and_no_optimistic_confirmation(self):
        device = {"type": 2, "series": "P1"}
        for cls, dp, enabled, disabled in (
            (switch.LeproCloudPlugPowerMemorySwitch, "d100", 2, 0),
            (switch.LeproCloudPlugLockSwitch, "d102", 1, 0),
            (
                switch.LeproCloudPlugIndicatorLightSwitch,
                "d101",
                "100000000",
                "000000000",
            ),
        ):
            entity = cls(self.co, "plug", device)
            entity.hass = self.hass
            await entity.async_turn_on()
            self.assertEqual(self.broker.messages[-1][1]["d"], {dp: enabled})
            self.assertIsNone(entity.is_on)
            await self.report("plug", {dp: enabled, "online": 1})
            self.assertTrue(entity.is_on)
            await entity.async_turn_off()
            self.assertEqual(self.broker.messages[-1][1]["d"], {dp: disabled})

    async def test_ble_only_filter_and_packaged_catalog(self):
        self.assertFalse(is_supported_device({"type": 1, "control": 1}))
        self.assertTrue(is_supported_device({"type": 1, "control": 2}))
        self.assertTrue(is_supported_device({"type": 2, "control": 3}))
        self.assertFalse(is_supported_device({"type": 1, "control": 7}))
        self.assertEqual(len(PRODUCT_CONFIGS), 70)
        for value in BULB_PRESETS.values():
            scene_brightness(value, 100)

    async def test_diagnostics_excludes_account_identity_and_secrets(self):
        self.entry.runtime_data = self.co
        self.co.devices["lamp"].update(
            name="Private room", mac="private-mac", token="private-token"
        )
        self.co.states["lamp"] = {"d1": 1, "secret": "private-secret"}
        result = await diagnostics.async_get_config_entry_diagnostics(
            self.hass, self.entry
        )
        text = json.dumps(result)
        for value in (
            "Private room",
            "private-mac",
            "private-token",
            "private-secret",
            "audit@example",
            "unused",
        ):
            self.assertNotIn(value, text)
        self.assertEqual(result["devices"][0]["datapoints"], ["d1"])

    async def test_real_platform_setup_unload_reload_and_registry_cleanup(self):
        hass = self.hass
        loader.async_setup(hass)
        hass.config.components.add("persistent_notification")
        hass.config_entries = ConfigEntries(hass, {})
        await hass.config_entries.async_initialize()
        if hasattr(device_registry, "async_setup"):
            device_registry.async_setup(hass)
        await device_registry.async_load(hass)
        await area_registry.async_load(hass)
        await entity_registry.async_load(hass)
        await async_setup_component(hass, "homeassistant", {})
        kwargs = {
            "domain": "lepro_cloud",
            "title": "Audit",
            "data": self.entry.data,
            "options": {},
            "source": "user",
            "unique_id": self.entry.unique_id,
            "version": 1,
            "minor_version": 1,
            "discovery_keys": MappingProxyType({}),
            "subentries_data": [],
        }
        kwargs = {
            k: v
            for k, v in kwargs.items()
            if k in inspect.signature(ConfigEntry).parameters
        }
        entry = ConfigEntry(**kwargs)
        devices = {
            "p1": {"did": "p1", "type": 2, "series": "P1", "name": "Audit Plug"},
            "tb1": {"did": "tb1", "type": 1, "series": "TB1", "name": "Audit Lamp"},
            "stv": {"did": "stv", "type": 1, "series": "STV1", "name": "Audit TV"},
        }

        async def start(co):
            co.devices = {did: dict(value) for did, value in devices.items()}
            co.connected = True
            co._fresh = set(devices)
            co.states = {did: {"d1": 1, "online": 1} for did in devices}

        with patch.object(client.LeproCoordinator, "async_start", start):
            await hass.config_entries.async_add(entry)
            await hass.async_block_till_done()
            co = entry.runtime_data
            self.assertEqual(len(co.listeners), 11)
            registry = entity_registry.async_get(hass)
            self.assertEqual(
                len(
                    entity_registry.async_entries_for_config_entry(
                        registry, entry.entry_id
                    )
                ),
                11,
            )
            self.assertTrue(await hass.config_entries.async_unload(entry.entry_id))
            self.assertEqual(len(co.listeners), 0)
            devices.pop("p1")
            self.assertTrue(await hass.config_entries.async_setup(entry.entry_id))
            await hass.async_block_till_done()
            self.assertEqual(len(entry.runtime_data.listeners), 6)
            self.assertEqual(
                len(
                    entity_registry.async_entries_for_config_entry(
                        registry, entry.entry_id
                    )
                ),
                6,
            )
            self.assertTrue(await hass.config_entries.async_unload(entry.entry_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
