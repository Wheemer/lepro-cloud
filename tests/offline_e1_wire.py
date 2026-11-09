"""Exercise real Paho and HTTPS discovery against loopback fixture servers.

Requires the CI test dependencies and OpenSSL. Uses only HA import stubs.
Pass a permanent server research directory via --work-dir. No vendor login,
Home Assistant instance, real device, or live configuration is accessed.
"""

import asyncio
import json
import ssl
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import paho.mqtt.client as real_mqtt
from aiohttp import web

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from test_platform_devices import _load_module

client = _load_module("client")
light = _load_module("light")
client.mqtt = real_mqtt
DID = "910030"
RED = "N01:P10001FF0000F210001001EU3V3000640000E1;"
GREEN = "N01:P1000100FF00F210001001EU3V3000640000E1;"
events = []


def packet(kind, payload):
    n = len(payload)
    length = bytearray()
    while True:
        b = n % 128
        n //= 128
        length.append(b | (128 if n else 0))
        if not n:
            break
    return bytes([kind]) + bytes(length) + payload


def text(s):
    b = s.encode()
    return len(b).to_bytes(2, "big") + b


async def read_packet(reader):
    h = (await reader.readexactly(1))[0]
    n = 0
    mult = 1
    while True:
        b = (await reader.readexactly(1))[0]
        n += (b & 127) * mult
        if not b & 128:
            break
        mult *= 128
    return h, await reader.readexactly(n)


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.01)


class Harness:
    def __init__(self, loop):
        self.loop = loop
        self.data = {}
        self.reloads = []
        self.config_entries = SimpleNamespace(async_schedule_reload=self.reloads.append)

    async def async_add_executor_job(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    def async_create_background_task(self, coro, name):
        return asyncio.create_task(coro, name=name)


async def main():
    key = WORK / "fixture-key.pem"
    cert = WORK / "fixture-cert.pem"
    if not key.exists():
        await asyncio.to_thread(
            subprocess.run,
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "2",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        key.chmod(0o600)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    tls.verify_mode = ssl.CERT_REQUIRED
    tls.load_verify_locations(cert)
    http_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    http_tls.load_cert_chain(cert, key)
    command_seen = asyncio.Event()
    release_report = asyncio.Event()
    subscriptions = set()
    commands = []
    broker_writers = []

    async def broker(reader, writer):
        broker_writers.append(writer)
        try:
            while True:
                h, b = await read_packet(reader)
                kind = h >> 4
                if kind == 1:
                    events.append(
                        {
                            "mqtt": "CONNECT",
                            "mutual_tls": bool(writer.get_extra_info("peercert")),
                        }
                    )
                    writer.write(packet(0x20, b"\x00\x00"))
                elif kind == 8:
                    mid = b[:2]
                    offset = 2
                    count = 0
                    while offset < len(b):
                        n = int.from_bytes(b[offset : offset + 2], "big")
                        offset += 2
                        topic = b[offset : offset + n].decode()
                        offset += n
                        qos = b[offset]
                        offset += 1
                        count += 1
                        subscriptions.add(topic)
                        events.append({"mqtt": "SUBSCRIBE", "topic": topic, "qos": qos})
                    writer.write(packet(0x90, mid + bytes([0]) * count))
                elif kind == 3:
                    n = int.from_bytes(b[:2], "big")
                    topic = b[2 : 2 + n].decode()
                    data = json.loads(b[2 + n :])
                    events.append(
                        {
                            "mqtt": "PUBLISH_FROM_INTEGRATION",
                            "topic": topic,
                            "payload": data,
                        }
                    )
                    if topic.endswith("/get"):
                        assert {"d50", "d52", "d53"} <= set(data["d"])
                        target = f"le/{DID}/prp/{REPLY_SUFFIX}"
                        assert target in subscriptions
                        # Deliberately include c alongside d: the APK dispatches this as state.
                        response = {
                            "id": data["id"],
                            "c": 0,
                            "d": {
                                "d1": 1,
                                "d2": INITIAL_MODE,
                                "d3": 0,
                                "d4": 0,
                                "d5": "000000000000",
                                "d50": RED,
                                "d52": 500,
                                "d53": 30,
                            },
                        }
                        writer.write(
                            packet(0x30, text(target) + json.dumps(response).encode())
                        )
                        events.append(
                            {
                                "mqtt": "DEVICE_STATE_REPLY",
                                "topic": target,
                                "payload": response,
                            }
                        )
                    elif topic.endswith("/set"):
                        commands.append(data["d"])
                        command_seen.set()
                        ack = {"id": data["id"], "c": 0}
                        writer.write(
                            packet(
                                0x30,
                                text(f"le/{DID}/prp/setr") + json.dumps(ack).encode(),
                            )
                        )
                        await release_report.wait()
                        target = f"le/{DID}/prp/rpt"
                        report = {"d": data["d"]}
                        writer.write(
                            packet(0x30, text(target) + json.dumps(report).encode())
                        )
                        events.append(
                            {"mqtt": "DEVICE_RPT", "topic": target, "payload": report}
                        )
                elif kind == 12:
                    writer.write(packet(0xD0, b""))
                elif kind == 14:
                    break
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        except (AssertionError, ValueError, KeyError, OSError) as error:
            events.append({"broker_error": repr(error)})
        finally:
            writer.close()

    mqtt_server = await asyncio.start_server(broker, "127.0.0.1", 0, ssl=tls)
    port = mqtt_server.sockets[0].getsockname()[1]

    async def api_handler(request):
        path = request.path
        events.append({"http": request.method, "path": path})
        if path == "/user/profile":
            data = {
                "mqtt": {
                    "host": "127.0.0.1",
                    "port": port,
                    "root": cert.read_text(),
                    "cert": cert.read_text(),
                }
            }
        elif path.startswith("/family/list/"):
            data = {"list": [{"fid": "owner"}, {"fid": "shared"}]}
        elif path.startswith("/v3/device/list/fid/owner/"):
            data = {
                "list": [
                    {
                        "did": DID,
                        "type": 1,
                        "control": 2,
                        **(
                            {"series": DEVICE_SERIES}
                            if DEVICE_SERIES is not None
                            else {}
                        ),
                        **({"proId": PRODUCT_ID} if PRODUCT_ID is not None else {}),
                        "fid": "owner",
                        "name": "Fixture",
                    }
                ]
            }
        elif path.startswith("/v3/device/list/fid/shared/"):
            data = {"list": [{"did": DID, "type": None, "series": ""}]}
        elif path == "/pub/resources/config.series.json":
            return web.json_response(
                [{"series": "E1-30", "colorPicker": "diyEaves", "effect": "striplight"}]
            )
        elif path.startswith("/v3/scene/list/"):
            fid = path.split("/fid/")[1].split("/")[0]
            data = {"list": []}
            if "/cid/0/" in path:
                data = {
                    "list": [
                        {
                            "cid": 1 if fid == "owner" else 2,
                            "name": fid + " favorite",
                            "striplight": {"dp": "d50", "res": GREEN},
                        }
                    ]
                }
        else:
            raise web.HTTPNotFound()
        return web.json_response({"code": 0, "data": data})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", api_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=http_tls)
    await site.start()
    api_port = site._server.sockets[0].getsockname()[1]
    trust = ssl.create_default_context(cafile=str(cert))
    original_tmp = client.tempfile.TemporaryDirectory
    co = None
    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=trust)
        ) as session:
            hass = Harness(asyncio.get_running_loop())
            api = client.LeproApi.__new__(client.LeproApi)
            api._session = session
            api._host = f"127.0.0.1:{api_port}"
            api.token = "fixture-token"
            api.secret = "fixture-secret"
            api.uid = "fixture-uid"
            entry = SimpleNamespace(
                data={"region": "europe"},
                entry_id="fixture",
                unique_id="fixture",
                async_start_reauth=lambda h: events.append({"unexpected_reauth": True}),
            )
            co = client.LeproCoordinator(hass, entry, api=api)
            with (
                patch.object(
                    client, "load_mqtt_private_key", return_value=key.read_text()
                ),
                patch.object(
                    client.tempfile,
                    "TemporaryDirectory",
                    lambda *a, **kw: original_tmp(*a, dir=str(WORK / "runtime"), **kw),
                ),
            ):
                await co.async_start()
            await until(lambda: co.device_available(DID))
            entry.runtime_data = co
            entities = []
            await light.async_setup_entry(
                hass, entry, lambda values: entities.extend(values)
            )
            assert len(entities) == 1
            entity = entities[0]
            entity.hass = hass
            await entity.async_added_to_hass()
            assert entity.supported_color_modes == {"hs", "color_temp"}
            assert entity.hs_color == (0.0, 100.0) and entity.brightness == 128, {
                "brightness": entity.brightness,
                "hs": entity.hs_color,
                "color_mode": entity.color_mode,
                "state": co.states[DID],
            }
            assert set(entity.effect_list) == {"owner favorite", "shared favorite"}, (
                entity.effect_list
            )
            assert not commands, commands
            assert co.devices[DID]["fid"] == "owner", co.devices[DID]
            initial = dict(co.states[DID])
            # First dim directly from the initial report, before any colour
            # command can normalize a placeholder/legacy ordinary work mode.
            await entity.async_turn_on(brightness=128)
            await asyncio.wait_for(command_seen.wait(), 5)
            await until(lambda: not co._pending_commands)
            assert commands[-1] == {"d1": 1, "d2": 2, "d52": 502}, commands
            assert co.states[DID]["d52"] == 500, "ACK must not fabricate brightness"
            assert co.states[DID]["d50"] == RED
            release_report.set()
            await until(lambda: co.states[DID].get("d52") == 502)
            await entity.async_turn_on(hs_color=(120, 100), brightness=128)
            await until(
                lambda: len(commands) >= 2 and co.states[DID].get("d50") == GREEN
            )
            assert commands[-1] == {"d1": 1, "d2": 2, "d50": GREEN, "d52": 502}
            assert entity.hs_color == (120.0, 100.0)
            assert entity.brightness == 128 and entity.write_count >= 1
            await entity.async_turn_on(brightness=64)
            await until(lambda: len(commands) >= 3 and co.states[DID].get("d52") == 251)
            assert commands[-1] == {"d1": 1, "d2": 2, "d52": 251}, commands[-1]
            assert co.states[DID]["d50"] == GREEN
            await entity.async_turn_on(effect="shared favorite", brightness=128)
            await until(lambda: len(commands) >= 4 and co.states[DID].get("d52") == 502)
            assert commands[-1] == {"d1": 1, "d2": 2, "d50": GREEN, "d52": 502}
            await entity.async_turn_off()
            await until(lambda: len(commands) >= 5 and co.states[DID].get("d1") == 0)
            assert commands[-1] == {"d1": 0}
            await entity.async_turn_on()
            await until(lambda: len(commands) >= 6 and co.states[DID].get("d1") == 1)
            assert commands[-1] == {"d1": 1}
            result = {
                "initial_state": initial,
                "final_state": dict(co.states[DID]),
                "supported_modes": sorted(entity.supported_color_modes),
                "commands": commands,
                "subscriptions": sorted(subscriptions),
                "scene_names": entity.effect_list,
                "family_contexts": co.devices[DID]["_family_ids"],
                "http_requests": [x for x in events if "http" in x],
                "ha_instances_started": False,
                "reply_suffix": REPLY_SUFFIX,
                "real_paho": real_mqtt.__file__,
            }
            assert not hass.reloads
            for remove in entity.remove_callbacks:
                remove()
            await co.async_stop()
            co = None
            (WORK / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
    finally:
        if co is not None:
            await co.async_stop()
        release_report.set()
        for writer in broker_writers:
            writer.close()
        mqtt_server.close()
        await mqtt_server.wait_closed()
        await runner.cleanup()
        (WORK / "wire-transcript.json").write_text(json.dumps(events, indent=2) + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Offline HTTPS/mTLS/MQTT E1 transport regression; no HA instance"
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--reply-suffix",
        choices=("getr", "rpt", "setr", "dsr/app/getr"),
        default="getr",
    )
    parser.add_argument("--initial-mode", type=int, choices=(0, 1, 2), default=2)
    parser.add_argument("--product-id", type=int, choices=(68, 115))
    parser.add_argument("--device-series", default="E1-30")
    parser.add_argument("--omit-series", action="store_true")
    args = parser.parse_args()
    PRODUCT_ID = args.product_id
    DEVICE_SERIES = None if args.omit_series else args.device_series
    INITIAL_MODE = args.initial_mode
    REPLY_SUFFIX = args.reply_suffix
    WORK = args.work_dir.resolve() / f"run-{time.time_ns()}"
    WORK.mkdir(parents=True, exist_ok=False)
    (WORK / "runtime").mkdir(exist_ok=True)
    asyncio.run(main())
