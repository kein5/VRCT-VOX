"""The first real sentence and caption must not pay for the GPU driver's kernels."""

import http.server
import importlib
import json
from threading import Event, Thread
from types import SimpleNamespace

import pytest


def warmup():
    return importlib.import_module("models.speech_server.warmup")


def runtime():
    return importlib.import_module("models.speech_server.runtime")


def token():
    return importlib.import_module("models.tts.speechcpp_tts").CancelToken()


def rows(task, device="Vulkan1"):
    return [{"id": "m", "speech": {"task": task, "device": device}}]


ASR = [
    {"id": "q", "speech": {"task": "recognition", "device": "Vulkan1"}},
    {"id": "v", "speech": {"task": "detection", "device": "CPU"}},
]


@pytest.fixture
def server():
    seen = []
    state = SimpleNamespace(seen=seen, status=200, hold=None, port=0)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append((self.path, self.headers["Content-Type"], body))
            if state.hold is not None:
                state.hold.wait(5)
            if self.path == "/v1/audio/speech" and state.status == 200:
                payload = b"\x01\x00" * 480
                self.send_response(200)
                self.send_header("Content-Type", "audio/pcm")
                self.send_header("X-Sample-Rate", "48000")
            else:
                payload = json.dumps({"text": ""}).encode()
                self.send_response(state.status)
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    state.port = httpd.server_port
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield state
    if state.hold is not None:
        state.hold.set()
    httpd.shutdown()
    httpd.server_close()


def url(server):
    return f"http://127.0.0.1:{server.port}"


def test_speech_is_warmed_with_a_sentence_of_ordinary_length(server):
    assert warmup().warm_up("japanese", url(server), rows("synthesis"), token(), 5) is True
    [(path, _, body)] = server.seen
    request = json.loads(body)
    assert path == "/v1/audio/speech"
    assert request["voice"] == "none" and request["language"] == "ja"
    # A two-character sentence took 0.08 s on an empty cache and warmed nothing.
    assert len(request["input"]) >= 15


def test_recognition_is_warmed_with_six_seconds_of_noise(server):
    assert warmup().warm_up("asr", url(server), ASR, token(), 5) is True
    [(path, content_type, body)] = server.seen
    assert path == "/v1/audio/transcriptions"
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="model"\r\n\r\nq\r\n' in body
    assert b"RIFF" in body
    # Two seconds of noise took 1.5 s on an empty cache and warmed nothing.
    assert len(body) >= 6 * 16000 * 2


def test_the_noise_is_not_silence():
    noise = warmup().noise_wav()
    samples = noise[44:]
    assert max(samples) > 0 and len(set(samples)) > 16


@pytest.mark.parametrize(
    ("profile", "models"),
    [
        ("japanese", rows("synthesis", "CPU")),
        ("asr", [{"id": "q", "speech": {"task": "recognition", "device": "CPU"}}]),
        # No voice this server is known to accept has been checked.
        ("multilingual", rows("synthesis")),
    ],
)
def test_nothing_is_sent_when_there_is_nothing_known_to_warm(server, profile, models):
    assert warmup().warm_up(profile, url(server), models, token(), 5) is False
    assert server.seen == []


def test_no_time_left_sends_nothing(server):
    assert warmup().warm_up("japanese", url(server), rows("synthesis"), token(), 0) is False
    assert server.seen == []


@pytest.mark.parametrize(
    ("profile", "models"), [("japanese", rows("synthesis")), ("asr", ASR)]
)
def test_a_refused_request_only_means_no_warm_up(server, profile, models):
    server.status = 500
    assert warmup().warm_up(profile, url(server), models, token(), 5) is False


def test_a_server_that_went_away_only_means_no_warm_up():
    assert warmup().warm_up("asr", "http://127.0.0.1:9", ASR, token(), 1) is False


@pytest.mark.parametrize(
    ("profile", "models"), [("japanese", rows("synthesis")), ("asr", ASR)]
)
def test_cancelling_interrupts_a_warm_up_that_is_waiting(server, profile, models):
    server.hold = Event()
    cancel = token()
    results = []
    thread = Thread(
        target=lambda: results.append(
            warmup().warm_up(profile, url(server), models, cancel, 30)
        ),
        daemon=True,
    )
    thread.start()
    for _ in range(200):
        if server.seen:
            break
        Event().wait(0.01)
    assert server.seen
    cancel.cancel()
    thread.join(2)
    assert not thread.is_alive() and results == [False]


class _Child:
    def poll(self):
        return None


def _server(monkeypatch, profile="japanese", models=None):
    module = runtime()
    data = models or rows("synthesis")
    monkeypatch.setattr(
        module,
        "_json",
        lambda port, path, deadline: {"status": "ok"}
        if path == "/health"
        else {"data": data},
    )
    monkeypatch.setattr(module.listener_monitors, "own", lambda *a: object())
    server_ = module.SpeechServer(profile, dict(device="gpu"))
    server_._child = _Child()
    server_._state.update(state="preparing")
    return module, server_


def test_the_server_is_not_ready_until_the_warm_up_ends(monkeypatch):
    module, speech = _server(monkeypatch)
    release, entered = Event(), Event()

    def warm(profile, base, models, cancel, limit):
        entered.set()
        release.wait(5)
        return True

    monkeypatch.setattr(module, "warm_up", warm)
    speech._ready(50000, module.time.monotonic() + 60)
    assert entered.wait(2)
    assert speech.health()["state"] == "preparing"
    release.set()
    speech._warmup.join(2)
    assert speech.health() == dict(
        state="ready", base_url="http://127.0.0.1:50000", error_code=None
    )


def test_a_failed_warm_up_still_starts_the_server(monkeypatch):
    module, speech = _server(monkeypatch)

    def warm(*args):
        raise RuntimeError("driver")

    monkeypatch.setattr(module, "warm_up", warm)
    speech._ready(50000, module.time.monotonic() + 60)
    speech._warmup.join(2)
    assert speech.health()["state"] == "ready"


def test_the_warm_up_leaves_time_before_the_start_limit(monkeypatch):
    module, speech = _server(monkeypatch)
    limits = []
    monkeypatch.setattr(
        module, "warm_up", lambda p, b, m, c, limit: limits.append(limit) or True
    )
    speech._ready(50000, module.time.monotonic() + 40)
    speech._warmup.join(2)
    assert 30 < limits[0] < 40


def test_stopping_cancels_a_running_warm_up_and_stays_stopped(monkeypatch):
    module, speech = _server(monkeypatch)
    entered = Event()
    cancelled = []

    def warm(profile, base, models, cancel, limit):
        entered.set()
        for _ in range(500):
            if cancel.is_set():
                cancelled.append(True)
                return False
            Event().wait(0.01)
        return True

    monkeypatch.setattr(module, "warm_up", warm)
    speech._ready(50000, module.time.monotonic() + 60)
    assert entered.wait(2)
    speech.stop()
    speech._warmup.join(2)
    assert cancelled == [True]
    assert speech.health()["state"] != "ready"
    assert speech.health()["base_url"] is None


def test_a_low_latency_standby_waits_for_the_warm_up(monkeypatch):
    module, speech = _server(
        monkeypatch,
        models=[
            {
                "id": "m",
                "speech": {
                    "task": "synthesis",
                    "device": "Vulkan1",
                    "architecture": "irodori-tts",
                },
            }
        ],
    )
    speech.options["low_latency"] = True
    order = []

    class Standby:
        def __init__(self, url):
            pass

        def start(self):
            order.append("standby")

        def close(self):
            return True

    monkeypatch.setattr(module, "LowLatencyStandby", Standby)
    monkeypatch.setattr(
        module, "warm_up", lambda *a: order.append("warm") or True
    )
    speech._ready(50000, module.time.monotonic() + 60)
    speech._warmup.join(2)
    assert order == ["warm", "standby"]
