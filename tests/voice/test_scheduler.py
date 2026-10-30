from threading import Event
from time import monotonic, monotonic_ns, sleep

from models.audio_routing.audio_router import AudioRouter
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from models.voice_events import AudioFrame, SpeechMessageEvent


def until(predicate, timeout=2):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.005)
    assert predicate()


def event(id="one", **kwargs):
    return SpeechMessageEvent(id, kwargs.pop("source", "chat"), "こんにちは", source_language="Japanese", **kwargs)


class Sink:
    def __init__(self):
        self.data = []
        self.closed = []
    def write(self, pcm, token):
        token.check()
        self.data.append(pcm)
    def close(self, *, drain, token):
        self.closed.append(drain)


def test_fake_http_to_explicit_output_once(pcm_server):
    sink = Sink()
    opens = []
    def output(device, rate, channels):
        opens.append((device, rate, channels))
        return sink
    with pcm_server(rate="24000") as (url, requests):
        settings = VoiceSettings.from_dict({"mode": "original", "output_device": "virtual-cable", "japanese_url": url})
        bus = VoiceEventBus(settings, router=AudioRouter(output))
        try:
            assert bus.publish(event())
            assert not bus.publish(event())
            until(lambda: bus.status()["completed"] == 1)
            assert len(requests) == 1
            assert opens == [("virtual-cable", 24000, 1)]
            assert b"".join(sink.data) == b"\x01\x00\x02\x00"
            assert sink.closed == [True]
            assert bus.status()["last_first_write_ms"] is not None
        finally:
            assert bus.close()


def test_off_partial_and_remote_never_open_outputs():
    bus = VoiceEventBus()
    assert not bus.publish(event())
    assert bus._thread is None
    bus.configure(VoiceSettings(mode="original", output_device="cable"))
    for source in ("mic", "speaker", "ocr"):
        assert not bus.publish(event(source=source))
    assert not bus.publish(event(is_final=False))
    assert bus._thread is None
    bus.close()


def test_bounded_queue_cancel_and_old_generation():
    entered = Event()
    class BlockingProvider:
        def __init__(self, url):
            pass
        def synthesize_stream(self, text, voice, language, token):
            entered.set()
            token.wait(2)
            token.check()
            yield AudioFrame(b"\x01\x00", 48000)
    bus = VoiceEventBus(VoiceSettings(mode="original", output_device="cable"), provider_factory=BlockingProvider)
    try:
        old = bus.generation()
        bus.publish(event())
        assert entered.wait(1)
        for i in range(20):
            bus.publish(event(str(i)))
        assert bus.status()["queued"] == 4
        assert bus.status()["dropped"] == 16
        bus.cancel()
        assert not bus.publish(event("stale"), expected_generation=old)
        until(lambda: not bus.status()["active"])
        assert bus.status()["queued"] == 0
        assert bus.status()["cancelled"] == 1
    finally:
        assert bus.close()


def test_expired_jobs_do_not_speak():
    bus = VoiceEventBus(VoiceSettings(mode="original", output_device="cable"))
    try:
        bus.publish(event(timestamp_ns=monotonic_ns() - 6_000_000_000))
        until(lambda: bus.status()["dropped"] == 1)
        assert bus.status()["completed"] == 0
    finally:
        bus.close()


def test_errors_are_private_and_worker_recovers():
    attempts = []
    sink = Sink()
    class Provider:
        def __init__(self, url):
            pass
        def synthesize_stream(self, text, voice, language, token):
            attempts.append(text)
            if len(attempts) == 1:
                raise RuntimeError("secret spoken text / path / token")
            yield AudioFrame(b"\x01\x00", 48000)
    bus = VoiceEventBus(VoiceSettings(mode="original", output_device="cable"),
                        provider_factory=Provider, router=AudioRouter(lambda *args: sink))
    try:
        bus.publish(event())
        until(lambda: bus.status()["errors"] == 1)
        assert bus.status()["last_error"] == "audio_output_error"
        bus.publish(event("second"))
        until(lambda: bus.status()["completed"] == 1)
        assert bus.status()["last_error"] is None
    finally:
        bus.close()


def test_whole_request_deadline(pcm_server):
    release = Event()
    with pcm_server(before_chunk=lambda i: release.wait(1)) as (url, _):
        bus = VoiceEventBus(VoiceSettings(mode="original", output_device="cable", japanese_url=url), request_timeout=0.05)
        try:
            bus.publish(event())
            until(lambda: bus.status()["errors"] == 1)
            assert bus.status()["last_error"] == "request_timeout"
        finally:
            release.set()
            bus.close()
