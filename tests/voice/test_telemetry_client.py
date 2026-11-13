"""Usage events as the receiver takes them, against a stand-in that keeps the receiver's rules.

The receiver's contract (2026-11-13): POST /v1/events with X-Ingest-Key; a body is one event
or {"events": [...]} of at most 20; only "app_started" and "error" are taken, and "error"
needs error_code matching [A-Za-z0-9_.-]{1,64}. It answers 200 {"ok": true, "accepted": N},
401 without the key and 400 for a body that is not JSON. A field the receiver does not know
does not make it refuse the event (checked against the deployed receiver on 2026-11-14 with
"v" and "hw"). Nothing in these tests leaves the PC, and none asks the real hardware.
"""
import asyncio
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import re
import socket
import sys
from threading import Lock, Thread
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import errors
from models.telemetry import client as client_module
from models.telemetry import hardware as hardware_module
from models.telemetry import state as state_module
from models.telemetry.client import ENDPOINT, INGEST_KEY, IngestClient, build_event, locale_tag, system_properties

import test_controller_integration

# The production Controller with unrelated services stubbed, as the integration tests load it.
controller_module = test_controller_integration.controller_module
CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


class Receiver:
    def __init__(self, delay=0.0):
        owner = self
        self.requests, self.accepted, self.delay = [], [], delay

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                owner.requests.append((self.path, dict(self.headers), raw))
                time.sleep(owner.delay)
                if self.path != "/v1/events":
                    return self.answer(404, {"ok": False, "error": "not_found"})
                if self.headers.get("X-Ingest-Key") != INGEST_KEY:
                    return self.answer(401, {"ok": False, "error": "unauthorized"})
                try:
                    body = json.loads(raw)
                except ValueError:
                    return self.answer(400, {"ok": False, "error": "bad_json"})
                events = body["events"][:20] if isinstance(body, dict) and "events" in body else [body]
                taken = [event for event in events if isinstance(event, dict) and (
                    event.get("event") == "app_started"
                    or (event.get("event") == "error" and isinstance(event.get("error_code"), str)
                        and CODE.fullmatch(event["error_code"])))]
                owner.accepted += taken
                self.answer(200, {"ok": True, "accepted": len(taken)})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1/events"
        Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def receiver():
    made = []

    def make(**options):
        made.append(Receiver(**options))
        return made[-1]
    yield make
    for item in made:
        item.close()


HARDWARE = {"cpu": "12th Gen Intel(R) Core(TM) i7-1255U", "cores": 12, "ram_gb": 32, "gpus": [
    {"name": "Intel(R) Iris(R) Xe Graphics", "kind": "igpu", "vram_gb": 16, "driver": "32.0.101.7085"},
    {"name": "NVIDIA GeForce RTX 3060 Ti", "kind": "gpu", "vram_gb": 8, "driver": "32.0.16.2124"}]}
BASE = {"event", "v", "timestamp", "app_version", "os", "os_version", "locale"}


def started(url, hardware=None, **options):
    client = IngestClient(endpoint=url, **options)
    asyncio.run(client.start("0.1.0-beta.7", "ja", hardware))
    return client


def accepted(client, name, properties=None):
    """Whether the receiver took the event."""
    return asyncio.run(client.track(name, properties))[1]


def test_the_app_started_event_carries_where_it_came_from_and_nothing_else(receiver):
    target = receiver()
    client = started(target.url, HARDWARE)
    body, taken = asyncio.run(client.track("app_started"))
    assert taken is True
    (path, headers, raw), = target.requests
    event = json.loads(raw)
    # What track() hands back for the record is what went out.
    assert body == event
    assert path == "/v1/events" and headers["X-Ingest-Key"] == INGEST_KEY and headers["Content-Type"] == "application/json"
    assert set(event) == BASE | {"hw"}
    assert event["event"] == "app_started" and event["app_version"] == "0.1.0-beta.7" and event["locale"] == "ja-JP"
    assert event["v"] == 2 and event["hw"] == HARDWARE
    assert event["os"] in ("Windows", "Linux") and re.fullmatch(r"[\x20-\x7e]{1,64}", event["os_version"])
    # ISO 8601 in UTC, to the second, and the moment it was sent.
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", event["timestamp"])
    sent_at = datetime.strptime(event["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - sent_at).total_seconds()) < 60
    # No cookie, credential or identifier of the PC: only what HTTP needs, the key and the app's name.
    assert {name.lower() for name in headers} == {
        "host", "accept-encoding", "content-type", "content-length", "x-ingest-key", "user-agent"}
    assert headers["User-Agent"] == "VRCT-VOX"
    assert target.accepted == [event]


def test_an_error_event_is_its_fixed_code_and_the_same_surroundings(receiver):
    target = receiver()
    client = started(target.url)
    assert accepted(client, "error", {"error_code": "VRAM_ERROR"}) is True
    event = target.accepted[0]
    # Without hardware to name (no bundled speech.cpp, say), the event simply has no "hw".
    assert set(event) == BASE | {"error_code"}
    assert event["event"] == "error" and event["error_code"] == "VRAM_ERROR"
    # Whatever else a caller passes along is not sent.
    assert accepted(client, "error", {"error_code": "speech_server.device-failed", "text": "private", "path": "C:\\x"}) is True
    assert "private" not in target.requests[-1][2].decode() and set(target.accepted[1]) == set(event)


@pytest.mark.parametrize("name,properties", [
    ("error", {}), ("error", {"error_code": ""}), ("error", {"error_code": "has space"}),
    ("error", {"error_code": "C:\\Users\\someone"}), ("error", {"error_code": "x" * 65}), ("error", {"error_code": 7}),
    ("error", None), ("message_sent", {}), ("app_closed", {}), ("", {}), (None, {}),
])
def test_anything_but_the_two_events_is_not_sent_at_all(receiver, name, properties):
    target = receiver()
    client = started(target.url)
    assert asyncio.run(client.track(name, properties)) == (None, False)
    assert target.requests == []


def test_nothing_is_sent_before_start_or_after_stop(receiver):
    target = receiver()
    client = IngestClient(endpoint=target.url)
    assert asyncio.run(client.track("app_started")) == (None, False)

    async def lifecycle():
        await client.start("1.0", "en")
        await client.stop()
        return await client.track("app_started")
    assert asyncio.run(lifecycle()) == (None, False) and target.requests == []


def test_a_receiver_that_refuses_fails_or_stalls_only_means_the_event_was_not_sent(receiver):
    refused = receiver()
    assert accepted(started(refused.url, key="wrong"), "app_started") is False
    assert len(refused.requests) == 1 and refused.accepted == []
    slow = receiver(delay=3.0)
    began = time.monotonic()
    assert accepted(started(slow.url, timeout=0.3), "app_started") is False
    assert time.monotonic() - began < 2.0
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    # The event that did not arrive is still handed back, so the record can say so.
    body, taken = asyncio.run(started(f"http://127.0.0.1:{port}/v1/events", timeout=1).track("app_started"))
    assert taken is False and body["event"] == "app_started"


@pytest.mark.parametrize("endpoint", [
    "", "http://example.com/v1/events", "http://localhost/v1/events", "ftp://127.0.0.1/v1/events",
    "https://user:secret@example.com/v1/events", "https://example.com/v1/events?key=1", "https://example.com", "not a url",
])
def test_events_go_over_https_or_to_this_pc_only(endpoint, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a connection was opened")
    monkeypatch.setattr(client_module.http.client, "HTTPConnection", refuse)
    monkeypatch.setattr(client_module.http.client, "HTTPSConnection", refuse)
    client = started(endpoint)
    assert asyncio.run(client.track("app_started")) == (None, False) and client.endpoint is None


def test_the_receiver_is_vrct_voxs_own_over_tls(monkeypatch):
    assert ENDPOINT == "https://vrct-vox-telemetry.kei9d09.workers.dev/v1/events"
    assert re.fullmatch(r"[0-9a-f]{48}", INGEST_KEY)
    opened = []

    class Connection:
        def __init__(self, host, port, timeout, context):
            opened.append((host, port, context is not None))

        def request(self, *args, **kwargs):
            raise OSError("no network in this test")

        def close(self):
            pass

    def plain(*args, **kwargs):
        raise AssertionError("plain HTTP was used for the receiver")
    monkeypatch.delenv(client_module.ENDPOINT_OVERRIDE, raising=False)
    monkeypatch.setattr(client_module.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(client_module.http.client, "HTTPConnection", plain)
    client = IngestClient()
    client.prepare()
    asyncio.run(client.start("1.0", "ja"))
    assert accepted(client, "app_started") is False
    assert opened == [("vrct-vox-telemetry.kei9d09.workers.dev", 443, True)]
    # What the user is shown as the destination is where it goes.
    assert client.endpoint == ENDPOINT


@pytest.mark.parametrize("override,used", [
    ("http://127.0.0.1:8799/v1/events", "http://127.0.0.1:8799/v1/events"),
    # The variable is for a stand-in on the developer's PC: it cannot point anyone's events elsewhere.
    ("https://collector.example/v1/events", ENDPOINT),
    ("http://192.168.1.20/v1/events", ENDPOINT),
    ("nonsense", ENDPOINT), ("", ENDPOINT),
])
def test_the_endpoint_can_be_replaced_by_a_loopback_address_only(monkeypatch, override, used):
    monkeypatch.setenv(client_module.ENDPOINT_OVERRIDE, override)
    assert client_module._endpoint() == used


def test_the_display_language_travels_as_one_of_five_tags():
    assert [locale_tag(code) for code in ("en", "ja")] == ["en-US", "ja-JP"]
    # A UI language this version no longer has is reported as English.
    assert locale_tag("ko") == "en-US"
    assert locale_tag("") == "en-US" and locale_tag("fr") == "en-US" and locale_tag(None) == "en-US"
    properties = system_properties("0.1.0-beta.7", "ja")
    assert set(properties) == {"app_version", "os", "os_version", "locale"}
    assert system_properties("バージョン", "ja")["app_version"] == "unknown"
    assert system_properties("1.0", "ja", HARDWARE)["hw"] == HARDWARE
    assert "hw" not in system_properties("1.0", "ja", {}) and "hw" not in system_properties("1.0", "ja", "RTX")


def test_an_old_builds_key_file_and_sdk_are_never_touched(monkeypatch, receiver):
    import sys
    sdk = MagicMock()
    monkeypatch.setitem(sys.modules, "telemetry_keys", SimpleNamespace(APP_KEYS={"stable": "old", "beta": "old"}))
    monkeypatch.setitem(sys.modules, "aptabase", SimpleNamespace(Aptabase=sdk))
    reloaded = importlib.reload(client_module)
    target = receiver()
    client = reloaded.IngestClient(endpoint=target.url)
    asyncio.run(client.start("1.0", "ja"))
    assert asyncio.run(client.track("app_started"))[1] is True
    sdk.assert_not_called()
    assert "old" not in target.requests[0][2].decode() and target.requests[0][1]["X-Ingest-Key"] == reloaded.INGEST_KEY


@pytest.fixture
def telemetry_for(monkeypatch):
    """Fresh Telemetry objects that send to a given URL and are told the hardware, not asking for it."""
    from models import telemetry as package
    made = []

    def make(url, hardware=HARDWARE, hardware_delay=0.0):
        monkeypatch.setenv(client_module.ENDPOINT_OVERRIDE, url)
        package.Telemetry._instance = None
        telemetry = package.Telemetry()

        def source():
            time.sleep(hardware_delay)
            return json.loads(json.dumps(hardware))
        telemetry.hardware_source = source
        made.append(telemetry)
        return telemetry
    yield make
    for telemetry in made:
        telemetry.shutdown()
    package.Telemetry._instance = None


def settle(telemetry, timeout=8):
    """Waits until the telemetry thread has nothing left to send."""
    async def others():
        return len([task for task in asyncio.all_tasks() if task is not asyncio.current_task()])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if telemetry._loop is None or telemetry._run_async(others()) == 0:
            return
        time.sleep(0.02)
    raise AssertionError("telemetry did not settle")


def test_the_whole_module_sends_once_a_day_and_nothing_when_off(telemetry_for, receiver, tmp_path):
    target = receiver()
    storage = str(tmp_path / "telemetry_state.json")

    def seen():
        return [(event["event"], event.get("error_code"), event["locale"]) for event in target.accepted]

    telemetry = telemetry_for(target.url)
    telemetry.init(enabled=True, app_version="0.1.0-beta.7", storage_path=storage, locale="ja")
    telemetry.track_error("VRAM_ERROR")
    telemetry.track_error("VRAM_ERROR")
    settle(telemetry)
    assert seen() == [("app_started", None, "ja-JP"), ("error", "VRAM_ERROR", "ja-JP")]
    # Both carry the same hardware: an error can be set against the PCs that started.
    assert [event["hw"] for event in target.accepted] == [HARDWARE, HARDWARE]
    telemetry.shutdown()
    # The same day, another start: nothing new.
    again = telemetry_for(target.url)
    again.init(enabled=True, app_version="0.1.0-beta.7", storage_path=storage, locale="ja")
    again.track_error("VRAM_ERROR")
    settle(again)
    assert len(seen()) == 2
    again.shutdown()
    # Turned off: nothing, whatever happens.
    off = telemetry_for(target.url)
    off.init(enabled=False, app_version="0.1.0-beta.7", storage_path=str(tmp_path / "other.json"), locale="ja")
    off.track_error("DEVICE_NO_MIC")
    settle(off)
    assert len(seen()) == 2


def test_starting_does_not_wait_for_the_hardware_or_the_network(telemetry_for, receiver, tmp_path):
    target = receiver(delay=1.0)
    telemetry = telemetry_for(target.url, hardware_delay=0.5)
    began = time.monotonic()
    telemetry.init(enabled=True, app_version="0.1.0-beta.7", storage_path=str(tmp_path / "state.json"), locale="ja")
    # An error right away, before the hardware is known: it waits for it instead of going without.
    telemetry.track_error("VRAM_ERROR")
    assert time.monotonic() - began < 0.4
    settle(telemetry)
    assert [(event["event"], event["hw"]) for event in target.accepted] == [("app_started", HARDWARE), ("error", HARDWARE)]


def test_what_the_user_is_shown_is_what_is_sent_and_what_was_sent_is_kept(telemetry_for, receiver, tmp_path):
    target = receiver()
    storage = str(tmp_path / "telemetry_state.json")
    telemetry = telemetry_for(target.url)
    telemetry.state.set_storage_path(storage)
    # Before anything is sent, and without sending anything by asking.
    shown = telemetry.preview(app_version="0.1.0-beta.7", locale="ja")
    assert target.requests == [] and shown["sent"] == [] and shown["endpoint"] == target.url
    assert set(shown) == {"endpoint", "app_started", "sent"}
    telemetry.init(enabled=True, app_version="0.1.0-beta.7", storage_path=storage, locale="ja")
    telemetry.track_error("speech_server_out_of_memory")
    settle(telemetry)
    started_event, error_event = target.accepted

    def timeless(event):
        return {key: value for key, value in event.items() if key != "timestamp"}
    # Field for field what the notice showed; only the time is the moment of sending.
    assert list(shown["app_started"]) == list(started_event) and timeless(shown["app_started"]) == timeless(started_event)
    assert shown["app_started"]["timestamp"] <= started_event["timestamp"] <= error_event["timestamp"]
    assert timeless(error_event) == {**timeless(started_event), "event": "error", "error_code": "speech_server_out_of_memory"}
    sent = telemetry.preview(app_version="0.1.0-beta.7", locale="ja")["sent"]
    # The record is the event exactly as it went out, time included.
    assert [(row["body"], row["accepted"]) for row in sent] == [(started_event, True), (error_event, True)]
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", row["at"]) for row in sent)
    telemetry.shutdown()
    # The record outlives the app, and a later start reads it back.
    later = telemetry_for(target.url)
    later.state.set_storage_path(storage)
    assert later.preview(app_version="0.1.0-beta.7", locale="ja")["sent"] == sent


def test_an_event_that_did_not_arrive_is_recorded_as_such(telemetry_for, tmp_path):
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    telemetry = telemetry_for(f"http://127.0.0.1:{port}/v1/events")
    telemetry.init(enabled=True, app_version="0.1.0-beta.7", storage_path=str(tmp_path / "state.json"), locale="ja")
    settle(telemetry, timeout=15)
    (row,) = telemetry.preview(app_version="0.1.0-beta.7", locale="ja")["sent"]
    assert row["accepted"] is False and row["body"]["event"] == "app_started"


def test_only_the_latest_sent_events_are_kept(tmp_path):
    storage = str(tmp_path / "state.json")
    state = state_module.TelemetryState(storage)
    for number in range(state_module.SENT_LIMIT + 5):
        state.record_sent({"event": "error", "error_code": f"CODE_{number}"}, number % 2 == 0)
    state.record_sent("not an event", True)
    kept = state_module.TelemetryState(storage).sent()
    assert [row["body"]["error_code"] for row in kept] == [f"CODE_{number}" for number in range(5, state_module.SENT_LIMIT + 5)]
    # A record somebody damaged is dropped row by row, never trusted.
    data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    data["sent"] = [{"at": 1, "body": {}, "accepted": True}, "x", kept[0]]
    (tmp_path / "state.json").write_text(json.dumps(data), encoding="utf-8")
    assert state_module.TelemetryState(storage).sent() == [kept[0]]


def test_once_a_day_means_the_day_of_the_events_timestamp(monkeypatch):
    # 08:30 on the 14th in Japan is still the 13th in UTC, the day of the timestamp in the event.
    moment = datetime(2026, 11, 13, 23, 30, 5, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.astimezone().replace(tzinfo=None)
    monkeypatch.setattr(state_module, "datetime", Clock)
    assert state_module._today() == "2026-11-13"
    event = build_event("app_started", system_properties("1.0", "ja"), now=moment)
    assert event["timestamp"] == "2026-11-13T23:30:05Z" and event["timestamp"].startswith(state_module._today())
    # A time given in another zone is still written in UTC.
    from datetime import timedelta
    tokyo = moment.astimezone(timezone(timedelta(hours=9)))
    assert build_event("app_started", system_properties("1.0", "ja"), now=tokyo)["timestamp"] == "2026-11-13T23:30:05Z"


def test_after_it_is_stopped_an_error_is_neither_sent_nor_counted_as_sent(telemetry_for, receiver, tmp_path):
    target = receiver()
    telemetry = telemetry_for(target.url)
    telemetry.init(enabled=True, app_version="0.1.0-beta.7", storage_path=str(tmp_path / "state.json"), locale="ja")
    settle(telemetry)
    telemetry.shutdown()
    telemetry.track_error("VRAM_ERROR")
    assert telemetry.is_enabled() is False and telemetry.state.should_send_error_today("VRAM_ERROR") is True
    assert [event["event"] for event in target.accepted] == ["app_started"]


DEVICES = [
    dict(name="Vulkan0", description="Intel(R) Iris(R) Xe Graphics", kind="igpu", memory_total=17087799296, memory_free=1),
    dict(name="Vulkan1", description="NVIDIA GeForce RTX 3060 Ti", kind="gpu", memory_total=8638169088, memory_free=1),
    dict(name="CPU", description="12th Gen Intel(R) Core(TM) i7-1255U", kind="cpu", memory_total=34175598592, memory_free=1),
]
DRIVERS = {"Intel(R) Iris(R) Xe Graphics": "32.0.101.7085", "NVIDIA GeForce RTX 3060 Ti": "32.0.16.2124"}


def hardware_from(monkeypatch, devices, drivers=None, cores=12):
    def rows(timeout):
        if isinstance(devices, Exception):
            raise devices
        return devices
    monkeypatch.setattr(hardware_module, "_devices", rows)
    monkeypatch.setattr(hardware_module, "_drivers", lambda names: dict(drivers or {}))
    monkeypatch.setattr(hardware_module.os, "cpu_count", lambda: cores)
    return hardware_module.collect()


def test_the_hardware_is_the_cpu_the_memory_and_the_gpus_with_their_drivers(monkeypatch):
    assert hardware_from(monkeypatch, DEVICES, DRIVERS) == HARDWARE
    # Seen with only the Direct3D 12 mapping layer in place of a GPU's own Vulkan driver: the
    # layer wraps the adapter's name, and the adapter's driver is still the one at work.
    wrapped = [dict(row, description=f"Microsoft Direct3D12 ({row['description']})") if row["kind"] != "cpu" else row
               for row in DEVICES]
    similar = dict(DRIVERS, **{"NVIDIA GeForce RTX 3060": "1.0"})
    assert [(gpu["name"], gpu["driver"]) for gpu in hardware_from(monkeypatch, wrapped, similar)["gpus"]] == [
        ("Microsoft Direct3D12 (Intel(R) Iris(R) Xe Graphics)", "32.0.101.7085"),
        ("Microsoft Direct3D12 (NVIDIA GeForce RTX 3060 Ti)", "32.0.16.2124")]
    # It fits the receiver's printable-text rule and stays small.
    body = build_event("app_started", system_properties("0.1.0-beta.7", "ja", HARDWARE))
    assert len(json.dumps(body, separators=(",", ":"))) < 1024


def test_hardware_that_cannot_be_read_is_left_out_not_guessed(monkeypatch):
    # No bundled speech.cpp, or it failed: only what Python itself knows.
    assert hardware_from(monkeypatch, RuntimeError("speech_bundle_missing_or_invalid")) == {"cores": 12}
    assert hardware_from(monkeypatch, [], cores=None) == {}
    # A GPU whose memory or driver is unknown is still named.
    unknown = [dict(DEVICES[1], memory_total=None), dict(DEVICES[2], memory_total=None)]
    assert hardware_from(monkeypatch, unknown) == {
        "cpu": "12th Gen Intel(R) Core(TM) i7-1255U", "cores": 12, "gpus": [{"name": "NVIDIA GeForce RTX 3060 Ti", "kind": "gpu"}]}
    # A PC without a GPU says so with an empty list.
    assert hardware_from(monkeypatch, [DEVICES[2]])["gpus"] == []


def test_names_travel_as_short_printable_ascii_and_at_most_four_gpus(monkeypatch):
    many = [dict(name=f"Vulkan{index}", description=f"GPU {index}", kind="gpu", memory_total=2 ** 31, memory_free=1)
            for index in range(6)]
    assert [gpu["name"] for gpu in hardware_from(monkeypatch, many)["gpus"]] == ["GPU 0", "GPU 1", "GPU 2", "GPU 3"]
    odd = [dict(name="Vulkan0", description="グラフィックス  Radeon\tRX 7600 " + "x" * 80, kind="gpu", memory_total=2 ** 33, memory_free=1),
           dict(name="Vulkan1", description="名前だけ", kind="gpu", memory_total=2 ** 33, memory_free=1),
           dict(name="CPU", description="プロセッサ", kind="cpu", memory_total=2 ** 34, memory_free=1)]
    result = hardware_from(monkeypatch, odd, {odd[0]["description"]: "24.5.1 beta", "名前だけ": "1.0"})
    (gpu,) = result["gpus"]
    assert gpu["name"].startswith("Radeon RX 7600 x") and len(gpu["name"]) == 64 and re.fullmatch(r"[\x20-\x7e]+", gpu["name"])
    # A driver version that is not a plain version string is not sent.
    assert "driver" not in gpu and "cpu" not in result and result["ram_gb"] == 16


@pytest.mark.parametrize("size,step", [
    (34175598592, 32), (17087799296, 16), (8 * 2 ** 30 - 5 * 2 ** 20, 8), (65 * 2 ** 30, 64), (3 * 2 ** 29, 1), (2 ** 41, 1024)])
def test_memory_is_sent_as_the_nearest_common_size(size, step):
    assert hardware_module.memory_step(size) == step


def test_windows_driver_versions_come_from_the_display_adapters_only(monkeypatch):
    keys = {"0000": {"DriverDesc": "Intel(R) Iris(R) Xe Graphics", "DriverVersion": "32.0.101.7085"},
            "0001": {"DriverDesc": "NVIDIA GeForce RTX 3060 Ti", "DriverVersion": "32.0.16.2124"},
            "0002": {"DriverDesc": "No version here"}, "Properties": PermissionError(5, "denied")}
    opened = []

    class Key:
        def __init__(self, values):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def open_key(parent, name):
        opened.append(name)
        if isinstance(parent, Key):
            if isinstance(keys[name], Exception):
                raise keys[name]
            return Key(keys[name])
        return Key(None)

    def enum_key(root, index):
        if index >= len(keys):
            error = OSError("no more")
            error.winerror = 259
            raise error
        return list(keys)[index]

    def query(key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        return key.values[name], 1
    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(
        HKEY_LOCAL_MACHINE="HKLM", OpenKey=open_key, EnumKey=enum_key, QueryValueEx=query))
    assert hardware_module._windows_drivers() == DRIVERS
    # One class key and its numbered children: nothing else in the registry is read.
    assert opened[0] == hardware_module._DISPLAY_CLASS and "4d36e968-e325-11ce-bfc1-08002be10318" in opened[0]
    assert set(opened[1:]) == set(keys)


def test_linux_names_only_the_nvidia_driver_version(monkeypatch):
    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return "550.120\n"
    paths = []
    monkeypatch.setattr(hardware_module, "open", lambda path, encoding=None: paths.append(path) or Stream(), raising=False)
    names = ["NVIDIA GeForce RTX 4070", "AMD Radeon RX 7600 (RADV NAVI33)"]
    assert hardware_module._linux_drivers(names) == {"NVIDIA GeForce RTX 4070": "550.120"}
    assert paths == ["/sys/module/nvidia/version"]

    def missing(path, encoding=None):
        raise FileNotFoundError(path)
    monkeypatch.setattr(hardware_module, "open", missing, raising=False)
    monkeypatch.setattr(hardware_module.sys, "platform", "linux")
    assert hardware_module._drivers(names) == {}


def test_the_hardware_is_asked_for_once(monkeypatch):
    calls = []
    monkeypatch.setattr(hardware_module, "_cached", None)
    monkeypatch.setattr(hardware_module, "collect", lambda timeout=3.0: calls.append(timeout) or {"cores": 4, "gpus": []})
    first = hardware_module.cached()
    first["gpus"].append("changed by a caller")
    assert hardware_module.cached() == {"cores": 4, "gpus": []} and len(calls) == 1


def test_voice_failures_are_reported_by_listed_codes_only(monkeypatch):
    seen = []

    def broken(code):
        raise RuntimeError("a hook that fails")
    monkeypatch.setattr(errors, "_error_report_hooks", [broken, seen.append])
    for area, code in [
        ("speech_server", "speech_server_out_of_memory"), ("speech_server", "C:\\Users\\someone\\model.gguf"),
        ("voice_conversion", "vc_capture_overrun"), ("voice_conversion", "a code added later"),
        ("realtime", "realtime_asr_timeout"), ("realtime", None),
        # A speech request that failed over its text or settings is the user's business, not a report.
        ("tts", "first_audio_timeout"), ("tts", "language_or_text_unavailable"), ("tts", "invalid_text"),
        ("somewhere else", "speech_server_out_of_memory"),
    ]:
        errors.report_failure(area, code)
    assert seen == ["speech_server_out_of_memory", "speech_server_failed_other", "vc_capture_overrun",
                    "voice_conversion_failed_other", "realtime_asr_timeout", "realtime_failed_other", "first_audio_timeout"]
    # Everything that can be reported is a code the receiver takes.
    for codes, other in errors.REPORTED_FAILURES.values():
        assert all(CODE.fullmatch(code) for code in codes) and (other is None or CODE.fullmatch(other))
    # The wrapper the audio code calls reaches the same list, and never raises.
    from models.failure_report import report_failure
    report_failure("voice_conversion", "vc_worker_eof")
    assert seen[-1] == "vc_worker_eof"
    monkeypatch.setattr(errors, "report_failure", broken)
    report_failure("voice_conversion", "vc_worker_eof")


def test_a_failed_caption_session_and_a_stopped_conversion_report_once(monkeypatch):
    from models.transcription import realtime_session
    from models.voice_conversion import process
    reported = []
    monkeypatch.setattr(realtime_session, "report_failure", lambda area, code: reported.append((area, code)))
    monkeypatch.setattr(process, "report_failure", lambda area, code: reported.append((area, code)))
    session = object.__new__(realtime_session.RealtimeSession)
    session._lock, session._state, session._error, session.request_stop = Lock(), "running", None, lambda: None
    session._fail("realtime_asr_timeout")
    session._fail("realtime_capture_stop_failed")
    assert reported == [("realtime", "realtime_asr_timeout")] and session._state == "failed"

    class Token:
        def __init__(self, stopping):
            self.stopping = stopping

        def is_set(self):
            return self.stopping
    reported.clear()
    conversion = object.__new__(process.VCProcess)
    conversion._lock, conversion._token, conversion.stop = Lock(), Token(False), lambda: None
    conversion._late, conversion._ages, conversion._rounds, conversion._blocks = deque(), deque(), deque(), 0
    conversion._fail("vc_capture_overrun")
    assert reported == [("voice_conversion", "vc_capture_overrun")] and conversion._state == "failed"
    # Stopped by the user: the same path runs, and it is not a failure.
    reported.clear()
    conversion._token = Token(True)
    conversion._fail("vc_worker_failed")
    assert reported == []


def test_a_failed_speech_request_is_reported_by_its_code_and_a_refused_text_is_not(monkeypatch):
    from models.audio_routing.audio_router import AudioRouter
    from models.tts import tts_scheduler
    from models.tts.settings import VoiceSettings
    from models.tts.speechcpp_tts import SpeechError
    from models.voice_events import SpeechMessageEvent
    reported = []
    monkeypatch.setattr(tts_scheduler, "report_failure", lambda area, code: reported.append((area, code)))
    failures = [SpeechError("transport_error"), ValueError("the text itself"), RuntimeError("secret device path")]

    class Provider:
        def __init__(self, url):
            pass

        def synthesize_stream(self, text, voice, language, token):
            raise failures.pop(0)
            yield  # A generator, as the real provider is.

    class Sink:
        def write(self, pcm, token):
            pass

        def close(self, *, drain, token):
            pass
    bus = tts_scheduler.VoiceEventBus(VoiceSettings(mode="original", output_device="cable"),
                                      provider_factory=Provider, router=AudioRouter(lambda *args: Sink()))
    try:
        for number in range(3):
            bus.publish(SpeechMessageEvent(f"event-{number}", "chat", "こんにちは", source_language="Japanese"))
            deadline = time.monotonic() + 3
            while bus.status()["errors"] <= number and time.monotonic() < deadline:
                time.sleep(0.005)
        assert bus.status()["errors"] == 3
    finally:
        bus.close()
    # What reaches the report is the fixed code; the list in errors.py then drops the middle one.
    assert reported == [("tts", "transport_error"), ("tts", "language_or_text_unavailable"), ("tts", "audio_output_error")]
    assert errors.reported_failure_code("tts", "language_or_text_unavailable") is None


def test_the_backend_answers_what_is_sent_without_sending(controller_module):
    c = configured(controller_module, True, 0)
    controller_module.model.telemetryPreview.return_value = {"endpoint": ENDPOINT, "app_started": {"event": "app_started"}, "sent": []}
    assert c.getTelemetryPreview() == {"status": 200, "result": controller_module.model.telemetryPreview.return_value}
    controller_module.model.telemetryPreview.assert_called_once_with(app_version="0.1.0-beta.7")
    # Asking is not an answer to the notice and starts nothing.
    assert c.getTelemetryNotice()["result"]["pending"] is True
    controller_module.model.telemetryInit.assert_not_called()


def configured(module, enabled, notice):
    module.config.ENABLE_TELEMETRY, module.config.TELEMETRY_NOTICE, module.config.VERSION = enabled, notice, "0.1.0-beta.7"
    module.model = MagicMock()
    return module.Controller


def test_nothing_is_sent_until_the_user_has_answered_the_notice(controller_module):
    c = configured(controller_module, True, 0)
    # On by default, and still nothing may be sent: the notice is pending.
    assert c._telemetryAllowed() is False
    assert c.getTelemetryNotice() == {"status": 200, "result": {"pending": True, "enabled": True}}
    # A settings file from before the notice carries "off" that nobody chose: it is asked all the same.
    c = configured(controller_module, False, 0)
    assert c._telemetryAllowed() is False and c.getTelemetryNotice()["result"]["pending"] is True
    controller_module.model.telemetryInit.assert_not_called()


@pytest.mark.parametrize("before", [True, False])
def test_the_answer_to_the_notice_sets_the_choice_and_only_then_starts_sending(controller_module, before):
    c = configured(controller_module, before, 0)
    assert c.setTelemetryNotice({"send": True}) == {"status": 200, "result": {"pending": False, "enabled": True}}
    assert c._telemetryAllowed() is True
    controller_module.model.telemetryInit.assert_called_once_with(enabled=True, app_version="0.1.0-beta.7")
    c = configured(controller_module, before, 0)
    assert c.setTelemetryNotice({"send": False}) == {"status": 200, "result": {"pending": False, "enabled": False}}
    assert c._telemetryAllowed() is False
    controller_module.model.telemetryInit.assert_not_called()
    controller_module.model.telemetryShutdown.assert_called_once_with()


@pytest.mark.parametrize("data", [None, {}, {"send": "yes"}, {"send": 1}, {"send": True, "extra": 1}, [True], "true"])
def test_an_answer_that_is_not_a_plain_yes_or_no_changes_nothing(controller_module, data):
    c = configured(controller_module, True, 0)
    assert c.setTelemetryNotice(data) == {"status": 400, "result": {"error_code": "telemetry_notice_invalid"}}
    assert controller_module.config.TELEMETRY_NOTICE == 0 and c._telemetryAllowed() is False
    controller_module.model.telemetryInit.assert_not_called()


@pytest.mark.parametrize("value,forced", [("off", True), (" OFF ", True), ("", False), ("on", False), ("0", False)])
def test_the_environment_can_turn_it_off_for_good_and_then_nothing_is_asked_either(controller_module, monkeypatch, value, forced):
    monkeypatch.setenv("VRCT_TELEMETRY", value)
    c = configured(controller_module, True, 0)
    assert c.getTelemetryNotice()["result"]["pending"] is (not forced)
    # Even an answer of "send", or the switch in the settings, starts nothing while it is forced off.
    c.setTelemetryNotice({"send": True})
    c.setEnableTelemetry()
    assert c._telemetryAllowed() is (not forced)
    assert controller_module.model.telemetryInit.called is (not forced)


def test_the_switch_in_the_settings_is_an_answer_of_its_own(controller_module):
    c = configured(controller_module, True, 0)
    assert c.setDisableTelemetry() == {"status": 200, "result": False}
    assert c.getTelemetryNotice()["result"] == {"pending": False, "enabled": False}
    controller_module.model.telemetryShutdown.assert_called_once_with()
    assert c.setEnableTelemetry() == {"status": 200, "result": True}
    assert c._telemetryAllowed() is True
    controller_module.model.telemetryInit.assert_called_once_with(enabled=True, app_version="0.1.0-beta.7")
