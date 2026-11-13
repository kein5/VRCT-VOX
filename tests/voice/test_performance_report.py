"""Performance reports: what may be sent, how a session adds up, and the one request that carries it.

fixtures/performance_report_v1.json is the example the receiver is tested against as well,
so the two sides cannot drift apart unnoticed.
"""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
from threading import Thread
import time

import pytest

from models.performance_report import report as report_module
from models.performance_report import sender
from models.performance_report.collector import RESERVOIR, Collector
from models.performance_report.schema import COUNTERS, FEATURES, TIMINGS, ascii_text, fault_of

EXAMPLE = json.loads((Path(__file__).parent / "fixtures" / "performance_report_v1.json").read_text(encoding="utf-8"))


def example(**changes):
    return {**copy.deepcopy(EXAMPLE), **changes}


def test_the_shared_example_may_be_sent_and_names_every_kind_of_field():
    assert fault_of(EXAMPLE) is None
    assert set(EXAMPLE["features"]) <= set(FEATURES)
    assert set(EXAMPLE["timings"]) <= set(TIMINGS) and set(EXAMPLE["counters"]) <= set(COUNTERS)
    everything = example(
        features={name: {"used_s": 1} for name in FEATURES},
        timings={name: {"n": 1, "p50": 0, "p95": 0, "max": 0} for name in TIMINGS},
        counters={name: 0 for name in COUNTERS})
    assert fault_of(everything) is None
    assert fault_of(example(gpus=[], features={}, timings={}, counters={}, errors={})) is None


SECRET = "C:\\Users\\someone\\private voice.wav"


def _change(path, value):
    def apply(report):
        target = report
        for key in path[:-1]:
            target = target[key]
        if value is _DELETE:
            del target[path[-1]]
        else:
            target[path[-1]] = value
    return apply


_DELETE = object()


@pytest.mark.parametrize("field,change", [
    ("unknown_field", _change(["device_names"], [SECRET])),
    ("unknown_field", _change(["text"], SECRET)),
    ("schema", _change(["schema"], 2)),
    ("schema", _change(["schema"], True)),
    ("app_version", _change(["app_version"], "1.0 " + SECRET)),
    ("os", _change(["os"], "macos")),
    ("os_version", _change(["os_version"], "十")),
    ("session_id", _change(["session_id"], "not-a-session")),
    ("sequence", _change(["sequence"], -1)),
    ("uptime_s", _change(["uptime_s"], 1.5)),
    ("vrchat", _change(["vrchat"], "yes")),
    ("cpu", _change(["cpu", "user"], SECRET)),
    ("cpu", _change(["cpu", "logical"], _DELETE)),
    ("gpus", _change(["gpus", 0, "name"], "x" * 101)),
    ("gpus", _change(["gpus"], [EXAMPLE["gpus"][0]] * 9)),
    ("features", _change(["features", "microphone_name"], {"used_s": 1})),
    ("features", _change(["features", "tts", "model"], SECRET)),
    ("features", _change(["features", "tts", "device"], "Vulkan 1")),
    ("features", _change(["features", "tts", "used_s"], _DELETE)),
    ("timings", _change(["timings", "caption_speaker_final_ms", "text"], SECRET)),
    ("timings", _change(["timings", "caption_speaker_final_ms", "p50"], float("inf"))),
    ("timings", _change(["timings", "made_up_ms"], {"n": 1, "p50": 1, "p95": 1, "max": 1})),
    ("counters", _change(["counters", "voice_blocks"], "many")),
    ("counters", _change(["counters", "words_spoken"], 3)),
    ("errors", _change(["errors", SECRET], 1)),
    ("errors", _change(["errors", "vc_capture_overrun"], 0)),
])
def test_a_report_that_holds_anything_outside_the_list_is_refused_whole(field, change):
    report = example()
    change(report)
    assert fault_of(report) == field
    assert sender.send("http://127.0.0.1:9/v1/report", report) is False  # never even tried


@pytest.mark.parametrize("report", [None, [EXAMPLE], "report", 1])
def test_only_an_object_is_a_report(report):
    assert fault_of(report) == "report"


def test_hardware_names_travel_as_printable_ascii_only():
    assert ascii_text("NVIDIA GeForce RTX 3060 Ti（外付け）", 100) == "NVIDIA GeForce RTX 3060 Ti"
    assert ascii_text("  12th Gen\tIntel(R)\nCore(TM)  i7-1255U ", 100) == "12th Gen Intel(R) Core(TM) i7-1255U"
    assert ascii_text("田中のGPU", 100) == "GPU"
    assert ascii_text("グラフィックス", 100) == "" and ascii_text(None, 100) == "" and ascii_text("x" * 200, 100) == "x" * 100


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_a_session_adds_up_how_long_each_feature_ran_and_where():
    clock = Clock()
    collector = Collector(clock)
    collector.feature("tts", True, device="Vulkan1", model="irodori-v41-q8")
    clock.now += 90.4
    collector.feature("captions_speaker", True, device="auto", model="custom")
    clock.now += 30
    collector.feature("tts", False)
    clock.now += 600
    collector.feature("tts", True, device="cpu", model="irodori-v41-q8")   # on again, elsewhere
    clock.now += 10
    collector.feature("ocr", False)                                        # never on: not in the report
    snapshot = collector.snapshot()
    assert snapshot["features"] == {
        "tts": {"used_s": 130, "device": "cpu", "model": "irodori-v41-q8"},
        # Still on: counted up to now.
        "captions_speaker": {"used_s": 640, "device": "auto", "model": "custom"},
    }
    with pytest.raises(ValueError):
        collector.feature("microphone_name", True)


def test_delays_are_summed_as_a_count_a_median_a_95th_percentile_and_a_maximum():
    collector = Collector(seed=1)
    for value in range(1, 101):
        collector.timing("caption_speaker_final_ms", value * 10)
    collector.timing("tts_first_audio_ms", 420.26)
    for bad in (-1, float("nan"), float("inf"), 10 ** 9, "12", None, True):
        collector.timing("tts_first_audio_ms", bad)
    assert collector.snapshot()["timings"] == {
        "caption_speaker_final_ms": {"n": 100, "p50": 500.0, "p95": 950.0, "max": 1000.0},
        "tts_first_audio_ms": {"n": 1, "p50": 420.3, "p95": 420.3, "max": 420.3},
    }
    with pytest.raises(ValueError):
        collector.timing("words_per_minute", 1)


def test_a_long_session_keeps_a_bounded_sample_and_the_true_count_and_maximum():
    collector = Collector(seed=7)
    for value in range(20_000):
        collector.timing("voice_roundtrip_ms", value % 100)
    collector.timing("voice_roundtrip_ms", 3000)
    summary = collector.snapshot()["timings"]["voice_roundtrip_ms"]
    assert summary["n"] == 20_001 and summary["max"] == 3000.0
    assert len(collector._timings["voice_roundtrip_ms"].samples) == RESERVOIR
    # A sample of an even spread: the median stays near the middle.
    assert 35 <= summary["p50"] <= 65 and 85 <= summary["p95"] <= 100


def test_counts_and_failure_codes_take_listed_names_and_fixed_codes_only():
    collector = Collector()
    collector.count("voice_blocks", 45_000)
    collector.count("voice_late_blocks")
    collector.count("voice_late_blocks", 211)
    for bad in (-1, 1.5, "2", None):
        collector.count("voice_blocks", bad)
    for code in ("vc_capture_overrun", "vc_capture_overrun", "speech_server_out_of_memory"):
        collector.error(code)
    for bad in (SECRET, "has space", "", None, 3, "x" * 65):
        collector.error(bad)
    snapshot = collector.snapshot()
    assert snapshot["counters"] == {"voice_blocks": 45_000, "voice_late_blocks": 212}
    assert snapshot["errors"] == {"vc_capture_overrun": 2, "speech_server_out_of_memory": 1}
    with pytest.raises(ValueError):
        collector.count("words_spoken")
    for index in range(80):
        collector.error(f"code_{index}")
    assert len(collector.snapshot()["errors"]) == 50


def build(**changes):
    values = dict(
        app_version="0.1.0-beta.7", os_name="windows", os_version="10.0.26220", session_id=EXAMPLE["session_id"],
        sequence=2, uptime_s=5400.9, vrchat=True,
        cpu={"model": " 12th Gen Intel(R) Core(TM) i7-1255U ", "logical": 12, "memory_gb": 31.84},
        gpus=[{"name": "Intel(R) Iris(R) Xe Graphics", "kind": "igpu", "memory_gb": 15.93},
              {"name": "NVIDIA GeForce RTX 3060 Ti（外付け）", "kind": "gpu", "memory_gb": 8.0}],
        snapshot={key: copy.deepcopy(EXAMPLE[key]) for key in ("features", "timings", "counters", "errors")})
    values.update(changes)
    return report_module.build(**values)


def test_a_session_and_the_parts_of_the_pc_make_the_shared_example():
    assert build() == EXAMPLE


def test_a_device_or_model_that_is_not_a_plain_identifier_is_left_out_not_sent():
    snapshot = {"features": {"tts": {"used_s": 5, "device": "Vulkan1", "model": SECRET},
                             "rvc": {"used_s": 9, "device": "cuda:0 (my card)", "model": "custom"},
                             "ocr": {"used_s": 1, "device": None}},
                "timings": {}, "counters": {}, "errors": {}}
    report = build(snapshot=snapshot)
    assert report["features"] == {"tts": {"used_s": 5, "device": "Vulkan1"}, "rvc": {"used_s": 9, "model": "custom"},
                                  "ocr": {"used_s": 1}}
    assert "someone" not in json.dumps(report) and fault_of(report) is None


def test_parts_without_a_usable_name_or_size_are_reported_as_unknown_or_left_out():
    report = build(cpu={"model": "プロセッサ", "logical": 0, "memory_gb": -1}, os_version="十一",
                   gpus=[{"name": "グラフィックス", "kind": "gpu", "memory_gb": 8}, {"name": "Some GPU", "kind": "weird", "memory_gb": "8"}])
    assert report["cpu"] == {"model": "unknown", "logical": 1, "memory_gb": 0.0} and report["os_version"] == "unknown"
    assert report["gpus"] == [{"name": "Some GPU", "kind": "other", "memory_gb": 0.0}]
    assert build(cpu=None, gpus=None)["gpus"] == []


@pytest.mark.parametrize("changes", [
    {"app_version": "1.0 beta"}, {"os_name": "macos"}, {"session_id": "short"}, {"sequence": -1},
    {"snapshot": {"features": {}, "timings": {}, "counters": {"words_spoken": 3}, "errors": {}}},
])
def test_a_report_that_still_holds_something_outside_the_list_is_never_built(changes):
    with pytest.raises(ValueError, match="performance_report_invalid:"):
        build(**changes)


class Receiver:
    """A local stand-in for the receiver: answers each post with the next status."""

    def __init__(self, statuses=(204,), delay=0.0):
        owner = self
        self.requests, self.statuses, self.delay = [], list(statuses), delay

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                owner.requests.append((self.path, dict(self.headers), body))
                time.sleep(owner.delay)
                status = owner.statuses.pop(0) if owner.statuses else 204
                self.send_response(status)
                if status == 302:
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1/report"
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


def test_one_post_carries_the_report_and_nothing_else_about_the_sender(receiver):
    target = receiver()
    assert sender.send(target.url, EXAMPLE) is True
    (path, headers, body), = target.requests
    assert path == "/v1/report" and json.loads(body) == EXAMPLE
    assert headers["Content-Type"] == "application/json" and headers["User-Agent"] == "VRCT-VOX"
    # No cookie, no credential, no identifier beyond the report itself.
    assert {name.lower() for name in headers} == {"host", "accept-encoding", "content-type", "content-length", "user-agent"}
    assert len(body) < 16 * 1024


@pytest.mark.parametrize("status,taken", [(204, True), (200, True), (400, False), (429, False), (500, False), (302, False)])
def test_only_a_success_counts_and_a_redirect_is_not_followed(receiver, status, taken):
    target = receiver(statuses=[status])
    assert sender.send(target.url, EXAMPLE) is taken
    assert len(target.requests) == 1


@pytest.mark.parametrize("endpoint", [
    "", None, "http://example.com/v1/report", "http://localhost/v1/report", "ftp://127.0.0.1/v1/report",
    "https://user:secret@example.com/v1/report", "https://example.com/v1/report?id=1", "https://example.com/v1/report#x",
    "https://example.com", "https://", "not a url", "http://127.0.0.1:99999/v1/report",
])
def test_nothing_is_sent_without_an_https_endpoint_or_a_loopback_one(endpoint, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a connection was opened")
    monkeypatch.setattr(sender.http.client, "HTTPConnection", refuse)
    monkeypatch.setattr(sender.http.client, "HTTPSConnection", refuse)
    assert sender.send(endpoint, EXAMPLE) is False


def test_an_https_endpoint_is_reached_over_tls_only(monkeypatch):
    opened = []

    class Connection:
        def __init__(self, host, port, timeout):
            opened.append((host, port, timeout))

        def request(self, *args, **kwargs):
            raise OSError("no network in this test")

        def close(self):
            opened.append("closed")

    def plain(*args, **kwargs):
        raise AssertionError("plain HTTP was used for an HTTPS endpoint")
    monkeypatch.setattr(sender.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(sender.http.client, "HTTPConnection", plain)
    assert sender.send("https://telemetry.example/v1/report", EXAMPLE, timeout=3) is False
    assert opened == [("telemetry.example", 443, 3), "closed"]


def test_a_receiver_that_does_not_answer_costs_the_timeout_and_no_more(receiver):
    target = receiver(delay=3.0)
    began = time.monotonic()
    assert sender.send(target.url, EXAMPLE, timeout=0.3) is False
    assert time.monotonic() - began < 2.0
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    assert sender.send(f"http://127.0.0.1:{port}/v1/report", EXAMPLE, timeout=1) is False


def test_a_report_larger_than_the_receiver_takes_is_not_sent(receiver, monkeypatch):
    target = receiver()
    monkeypatch.setattr(sender, "MAX_BODY_BYTES", 200)
    assert sender.send(target.url, EXAMPLE) is False and not target.requests
