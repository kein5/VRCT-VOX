"""Monitor output: same frames as the virtual microphone, never on its critical path."""
import sys
from threading import Event
from time import monotonic, sleep

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.audio_routing.monitor_output import MonitorTee, check_monitor_target, scale_pcm
from models.tts.settings import VoiceSettings
from models.tts.speechcpp_tts import CancelToken, SpeechError
from models.tts.tts_scheduler import VoiceEventBus
from models.voice_events import AudioFrame, SpeechMessageEvent


def until(predicate, timeout=2):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.005)
    assert predicate()


class Sink:
    def __init__(self, *, fail_after=None, gate=None):
        self.data, self.closed = [], []
        self.fail_after, self.gate = fail_after, gate

    def write(self, pcm, token):
        token.check()
        if self.gate is not None:
            while not self.gate.wait(0.01):
                token.check()
        if self.fail_after is not None and len(self.data) >= self.fail_after:
            raise SpeechError("output_disconnected")
        self.data.append(pcm)

    def close(self, *, drain, token):
        self.closed.append(drain)


class Opener:
    def __init__(self, sink=None, error=None):
        self.sink, self.error, self.calls = sink or Sink(), error, []

    def __call__(self, device, rate, channels, *, exclude=()):
        self.calls.append((device, rate, channels, exclude))
        if self.error is not None:
            raise self.error
        return self.sink


def pcm(seconds=0.2, rate=24000):
    return bytes((i * 7 + 1) % 256 for i in range(int(rate * seconds) * 2))


def play(main, monitor, data, rate=24000, token=None):
    first = []
    AudioRouter(lambda *args: main).play(iter([AudioFrame(data, rate)]), "cable", token or CancelToken(),
                                         lambda *args: first.append(args), monitor=monitor)
    return first


def test_monitor_gets_exactly_the_frames_sent_to_the_virtual_microphone():
    main, opener, errors = Sink(), Opener(), []
    data = pcm()
    monitor = MonitorTee("speakers", 100, exclude=("cable",), output_factory=opener, on_error=errors.append)
    first = play(main, monitor, data)
    assert monitor.join(2)
    assert b"".join(main.data) == data
    assert opener.sink.data == main.data  # Same blocks, same order.
    assert opener.calls == [("speakers", 24000, 1, ("cable",))]
    assert main.closed == [True] and opener.sink.closed == [True]
    assert len(first) == 1 and errors == []


@pytest.mark.parametrize("error", [SpeechError("output_missing"), OSError("device path detail")])
def test_monitor_open_failure_never_affects_main_output(error):
    main, errors = Sink(), []
    data = pcm()
    monitor = MonitorTee("gone", 100, output_factory=Opener(error=error), on_error=errors.append)
    first = play(main, monitor, data)
    assert monitor.join(2)
    assert b"".join(main.data) == data and main.closed == [True] and len(first) == 1
    # Fixed identifiers only; no device names or driver text.
    assert errors == ["monitor_output_missing" if isinstance(error, SpeechError) else "monitor_output_error"]


def test_monitor_unplugged_mid_stream_never_affects_main_output():
    main, errors = Sink(), []
    unplugged = Opener(Sink(fail_after=3))
    data = pcm()
    monitor = MonitorTee("usb", 100, output_factory=unplugged, on_error=errors.append)
    play(main, monitor, data)
    assert monitor.join(2)
    assert b"".join(main.data) == data and main.closed == [True]
    assert len(unplugged.sink.data) == 3 and errors == ["monitor_output_disconnected"]
    assert unplugged.sink.closed == [False]


def test_stalled_monitor_adds_no_wait_and_stays_bounded():
    gate = Event()
    stalled = Opener(Sink(gate=gate))
    main = Sink()
    data = pcm(seconds=2)
    monitor = MonitorTee("bluetooth", 100, output_factory=stalled, max_buffer_ms=100)
    started = monotonic()
    play(main, monitor, data)
    assert monotonic() - started < 1  # Fake main sink is instant; a blocked monitor must not pace it.
    assert b"".join(main.data) == data
    assert monitor.dropped > 0 and monitor._queued <= 24000 * 2 // 10
    gate.set()
    assert monitor.join(2)


def test_cancelled_speech_stops_the_monitor_without_draining():
    gate = Event()
    token = CancelToken()
    main = Sink()
    held = Opener(Sink(gate=gate))
    monitor = MonitorTee("speakers", 100, output_factory=held)
    original = main.write

    def cancel_after_first(pcm, guard):
        original(pcm, guard)
        token.cancel()
    main.write = cancel_after_first
    with pytest.raises(SpeechError, match="cancelled"):
        play(main, monitor, pcm(), token=token)
    assert monitor.join(2)
    assert held.sink.closed in ([False], [])
    assert held.sink.data == [] and monitor.error is None


def test_monitor_token_is_separate_from_the_main_start_deadline():
    seen = []

    class Recorder(Sink):
        def write(self, pcm, token):
            seen.append(token)
            super().write(pcm, token)
    main_token = CancelToken()
    monitor = MonitorTee("speakers", 100, output_factory=Opener(Recorder()))
    play(Sink(), monitor, pcm(0.05), token=main_token)
    assert monitor.join(2)
    assert seen and all(token is not main_token for token in seen)


def test_volume_scales_monitor_copy_only():
    main, opener = Sink(), Opener()
    data = (1000).to_bytes(2, "little", signed=True) * 240 + (-1000).to_bytes(2, "little", signed=True) * 240
    monitor = MonitorTee("speakers", 50, output_factory=opener)
    play(main, monitor, data)
    assert monitor.join(2)
    assert b"".join(main.data) == data
    assert b"".join(opener.sink.data) == scale_pcm(data, 50)
    assert scale_pcm(data, 50)[:2] == (500).to_bytes(2, "little", signed=True)
    assert scale_pcm(data, 50)[-2:] == (-500).to_bytes(2, "little", signed=True)
    assert scale_pcm(data, 100) is data and not any(scale_pcm(data, 0))


@pytest.mark.parametrize("target", ["vrct.managed.mix", "vrct.managed.tts", "vrct.source-bridge.x.playback", "cable", ""])
def test_monitor_never_targets_the_virtual_microphone(target):
    with pytest.raises(SpeechError):
        check_monitor_target(target, exclude=("cable",))
    assert check_monitor_target("alsa_output.headphones", exclude=("cable",)) == "alsa_output.headphones"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PipeWire default sink resolution")
def test_linux_default_monitor_resolves_default_sink_and_blocks_virtual_default(monkeypatch):
    from models.audio_routing import devices_pipewire, monitor_output
    graph = [{"type": "PipeWire:Interface:Metadata", "props": {"metadata.name": "default"},
              "metadata": [{"subject": 0, "key": "default.audio.sink", "type": "Spa:String:JSON",
                            "value": {"name": "alsa_output.speakers"}}]}]
    monkeypatch.setattr(devices_pipewire, "_dump", lambda: graph)
    opened = []
    monkeypatch.setattr(devices_pipewire, "PipeWireOutput",
                        lambda device, rate, channels, node_name: opened.append((device, node_name)) or Sink())
    monitor_output.open_monitor_output("", 24000, 1, exclude=("cable",))
    assert opened == [("alsa_output.speakers", "vrct.tts.monitor")]
    graph[0]["metadata"][0]["value"] = '{"name": "vrct.managed.mix"}'
    with pytest.raises(SpeechError, match="feedback_blocked"):
        monitor_output.open_monitor_output("", 24000, 1, exclude=("cable",))
    graph[0]["metadata"] = []
    with pytest.raises(SpeechError, match="output_missing"):
        devices_pipewire.default_output()


def test_windows_default_monitor_tolerates_underflow_and_blocks_the_cable(monkeypatch):
    from models.audio_routing import devices_windows, monitor_output
    opened = []
    default = ['["Windows WASAPI", "Speakers"]']
    monkeypatch.setattr(monitor_output.sys, "platform", "win32")
    monkeypatch.setattr(devices_windows, "default_output", lambda: default[0])
    monkeypatch.setattr(devices_windows, "WindowsOutput",
                        lambda device, rate, channels, strict_underflow: opened.append((device, strict_underflow)) or Sink())
    cable = '["Windows WASAPI", "CABLE Input"]'
    monitor_output.open_monitor_output("", 48000, 1, exclude=(cable,))
    assert opened == [(default[0], False)]
    default[0] = cable  # The user made the virtual cable their default output.
    with pytest.raises(SpeechError, match="feedback_blocked"):
        monitor_output.open_monitor_output("", 48000, 1, exclude=(cable,))


def test_monitor_settings_validate_and_default_off():
    assert VoiceSettings().monitor_choice is None
    legacy = VoiceSettings.from_dict({"mode": "original", "output_device": "cable"})
    assert legacy.monitor == "off" and legacy.monitor_choice is None
    chosen = VoiceSettings.from_dict({"output_device": "cable", "monitor": "on", "monitor_volume": "40"})
    assert chosen.monitor_choice == ("", 40)
    for bad in ({"monitor": "yes"}, {"monitor_volume": "101"}, {"monitor_volume": "-1"}, {"monitor_volume": ""},
                {"monitor_device": "vrct.managed.mix"}, {"monitor_device": "cable"},
                {"monitor_device": "a\nb"}, {"monitor_volume": 50}):
        with pytest.raises(ValueError):
            VoiceSettings.from_dict({"output_device": "cable", "monitor": "on", **bad})
    with pytest.raises(ValueError):
        VoiceSettings.from_dict({"routing": "managed", "monitor": "on", "monitor_device": "vrct.managed.tts"})
    # A leftover choice while off never blocks saving another output.
    assert VoiceSettings.from_dict({"output_device": "cable", "monitor_device": "cable"}).monitor_choice is None


class FakeProvider:
    def __init__(self, url):
        pass

    def synthesize_stream(self, text, voice, language, token, **options):
        yield AudioFrame(b"\x01\x00" * 480, 48000)


class RecordingRouter:
    def __init__(self):
        self.calls = []

    def play(self, frames, device, token, on_first_audio, **kwargs):
        self.calls.append(kwargs)
        main = Sink()
        AudioRouter(lambda *args: main).play(frames, device, token, on_first_audio, **kwargs)


def bus_for(settings, router, factory, **kwargs):
    return VoiceEventBus(VoiceSettings.from_dict(settings), provider_factory=FakeProvider, router=router,
                         monitor_factory=factory, **kwargs)


def say(bus, id="one"):
    assert bus.publish(SpeechMessageEvent(id, "chat", "こんにちは", source_language="Japanese"))


def test_disabled_monitor_opens_no_stream():
    factory_calls, router = [], RecordingRouter()
    bus = bus_for({"mode": "original", "output_device": "cable", "monitor_device": "speakers"}, router,
                  lambda *args, **kwargs: factory_calls.append(args))
    try:
        say(bus)
        until(lambda: bus.status()["completed"] == 1)
        assert factory_calls == [] and router.calls == [{}]
    finally:
        assert bus.close()


def test_enabled_monitor_failure_is_a_notice_not_a_speech_error():
    notices, router = [], RecordingRouter()
    opener = Opener(error=SpeechError("output_missing"))
    bus = bus_for({"mode": "original", "output_device": "cable", "monitor": "on", "monitor_volume": "80"},
                  router, lambda *args, **kwargs: MonitorTee(*args, output_factory=opener, **kwargs),
                  on_monitor_error=notices.append)
    try:
        say(bus)
        until(lambda: bus.status()["completed"] == 1 and bus.status()["monitor_error"] is not None)
        status = bus.status()
        assert status["errors"] == 0 and status["last_error"] is None
        assert status["monitor_error"] == "monitor_output_missing" and notices == ["monitor_output_missing"]
        assert opener.calls == [("", 48000, 1, ("cable",))]
        assert set(router.calls[0]) == {"monitor"}
        # A later successful open clears the notice; saving settings clears it too.
        opener.error = None
        say(bus, "two")
        until(lambda: bus.status()["completed"] == 2 and bus.status()["monitor_error"] is None)
    finally:
        assert bus.close()


def test_monitor_factory_crash_still_speaks():
    router = RecordingRouter()

    def broken(*args, **kwargs):
        raise RuntimeError("no threads")
    bus = bus_for({"mode": "original", "output_device": "cable", "monitor": "on"}, router, broken)
    try:
        say(bus)
        until(lambda: bus.status()["completed"] == 1)
        assert bus.status()["monitor_error"] == "monitor_output_error" and router.calls == [{}]
    finally:
        assert bus.close()
