"""Speech through the voice conversion (ADR-007): settings, the owner, the router and TTS."""
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from models.tts.converted_router import ConvertedSpeechRouter, to_conversion_rate
from models.tts.settings import VoiceSettings
from models.tts.speechcpp_tts import CancelToken, SpeechError
from models.voice_conversion import router_protocol as rp
from models.voice_conversion.direct_voice import DirectVoice
from models.voice_events import AudioFrame
from test_controller_integration import controller_module  # noqa: F401


def test_the_choice_is_off_by_default_and_cannot_mix_with_the_voice():
    assert VoiceSettings().conversion == "off"
    assert VoiceSettings.from_dict({"conversion": "on"}).conversion == "on"
    for bad in ({"conversion": "yes"}, {"conversion": "on", "direct_policy": "mix"}):
        with pytest.raises(ValueError):
            VoiceSettings.from_dict(bad)


def test_speech_frames_carry_one_block_at_most_and_nothing_else():
    pcm = b"\1\0" * 3840
    frame = rp.Reader.__new__(rp.Reader)
    import json
    value = json.loads(rp.speech_frame(pcm))
    assert rp.control_kind(value) == "speech" and rp.speech_pcm(value) == pcm
    for bad in (b"", b"\0", pcm + b"\0\0"):
        with pytest.raises(ValueError):
            rp.speech_frame(bad)
    for value in ({"kind": "speech", "pcm": "%%%"}, {"kind": "speech", "pcm": "AA==", "x": 1},
                  {"kind": "speech_end", "x": 1}, {"kind": "eval"}, "speech"):
        with pytest.raises(ValueError):
            kind = rp.control_kind(value)
            if kind == "speech":
                rp.speech_pcm(value)
    assert rp.control_kind({"kind": "speech_end"}) == "speech_end"
    assert rp.control_kind({"kind": "speech_cancel"}) == "speech_cancel"
    del frame


def test_a_monitor_control_may_name_the_direct_suppression():
    assert rp.validate_monitor_control({"kind": "monitor_mute", "muted": False, "revision": 3}) == (False, 3)
    assert rp.validate_monitor_control(
        {"kind": "monitor_mute", "muted": True, "suppressed": True, "revision": 4}) == (True, 4)
    with pytest.raises(ValueError):
        rp.validate_monitor_control({"kind": "monitor_mute", "muted": True, "suppressed": "yes", "revision": 4})


def test_speech_is_made_48_khz_mono_for_the_conversion():
    tone = (np.sin(np.arange(24000) * 2 * np.pi * 440 / 24000) * 8000).astype("<i2").tobytes()
    frames = [AudioFrame(tone[i:i + 4800], 24000) for i in range(0, len(tone), 4800)]
    out = b"".join(to_conversion_rate(frames))
    # One second at 24 kHz is one second at 48 kHz, within the resampler's edges.
    assert abs(len(out) // 2 - 48000) < 200
    stereo = AudioFrame(np.array([[100, 300]] * 480, dtype="<i2").tobytes(), 48000, 2)
    assert np.frombuffer(b"".join(to_conversion_rate([stereo])), dtype="<i2").tolist() == [200] * 480
    with pytest.raises(SpeechError, match="format_changed"):
        list(to_conversion_rate([AudioFrame(b"\0\0" * 10, 24000), AudioFrame(b"\0\0" * 10, 48000)]))


class FakeOwner:
    def __init__(self):
        self.calls, self.chunks = [], []

    def speaking_available(self):
        return True

    def speak(self, chunks, token, on_first_audio=None):
        for chunk in chunks:
            self.chunks.append(chunk)
            if on_first_audio is not None and len(self.chunks) == 1:
                on_first_audio(1, 48000)

    def set_direct_suppressed(self, value):
        self.calls.append(("suppressed", value))

    def set_monitor_muted(self, muted):
        self.calls.append(("muted", muted))

    def start(self, *, source):
        self.calls.append(("start", source))

    def stop(self):
        self.calls.append(("stop",))

    def health(self):
        return dict(requested=True, active=True)


def converted_voice():
    owner = FakeOwner()
    from models.audio_routing.source_bridge import Endpoint
    voice = DirectVoice(passthrough_factory=lambda **_: None, converted_factory=lambda options, **_: owner)
    voice.set_direct_suppressed(True)
    voice.start(source=Endpoint(1, 20, "test.mic", "Audio/Source"), expected_generation=0,
                mode="converted", options={})
    return voice, owner


def test_the_router_speaks_through_a_running_conversion_and_opens_no_device():
    voice, owner = converted_voice()
    assert ("suppressed", True) in owner.calls  # given before the start
    router = ConvertedSpeechRouter(voice)
    assert router.available()
    token, first = CancelToken(), []
    router.play([AudioFrame(b"\1\0" * 480, 48000)], "a-device", token, lambda *a: first.append(a))
    assert owner.chunks == [b"\1\0" * 480] and first == [(1, 48000)]


def test_without_a_conversion_the_router_is_unavailable():
    voice = DirectVoice(passthrough_factory=lambda **_: None)
    router = ConvertedSpeechRouter(voice)
    assert not router.available()
    with pytest.raises(SpeechError, match="conversion_unavailable"):
        router.play([], "", CancelToken(), lambda *a: None)


class Pipe:
    """The router end of the control pipe, taking writes whole or in parts."""
    def __init__(self, part=None):
        self.data, self.part = bytearray(), part

    def write(self, data):
        taken = data if self.part is None else data[:self.part]
        self.data.extend(taken)
        return len(taken)

    def frames(self):
        import json
        return [json.loads(line) for line in bytes(self.data).splitlines()]


def owner(part=None):
    from models.voice_conversion.isolated import IsolatedVCProcess
    proc = IsolatedVCProcess.__new__(IsolatedVCProcess)
    proc._lock, proc._stop = threading.Lock(), threading.Event()
    proc._state = dict(active=True)
    proc._controlled, proc._router_seen = True, True
    proc._monitor_muted, proc._direct_suppressed = True, False
    proc._monitor_revision = proc._sent_monitor_revision = 0
    proc._monitor_pending_since = None
    proc._out = bytearray()
    proc._stdin = Pipe(part)
    return proc


def flush(proc):
    for _ in range(10_000):
        proc._check_control()
        if not proc._out:
            return


@pytest.mark.parametrize("part", [None, 1000])
def test_frames_reach_the_router_whole_and_in_order_even_when_the_pipe_takes_parts(monkeypatch, part):
    from models.voice_conversion import isolated
    monkeypatch.setattr(isolated, "SPEECH_TAIL_NS", 0)
    proc = owner(part)
    speech = b"\1\0" * 3840 * 2 + b"\2\0" * 100
    proc.speak([speech[:5000], speech[5000:]], CancelToken())
    proc.set_direct_suppressed(True)
    flush(proc)
    frames = proc._stdin.frames()
    assert [f["kind"] for f in frames] == ["speech", "speech", "speech", "speech_end", "monitor_mute"]
    assert b"".join(rp.speech_pcm(f) for f in frames[:3]) == speech
    assert frames[-1]["suppressed"] is True


def test_speech_is_paced_to_real_time(monkeypatch):
    from models.voice_conversion import isolated
    monkeypatch.setattr(isolated, "SPEECH_TAIL_NS", 0)
    proc = owner()
    one_second = b"\1\0" * 48000
    started = time.monotonic()
    proc.speak([one_second], CancelToken())
    # Sent at most SPEECH_LEAD ahead: one second takes at least 0.6 s to hand over.
    assert time.monotonic() - started >= 1.0 - isolated.SPEECH_LEAD_NS / 1e9 - 0.05


def test_a_cancelled_or_stopped_speech_tells_the_router_to_drop_it():
    proc = owner()
    token = CancelToken()
    token.cancel()
    with pytest.raises(Exception):
        proc.speak([b"\1\0" * 3840], token)
    proc._state["active"] = False
    with pytest.raises(RuntimeError, match="vc_speech_unavailable"):
        proc.speak([b"\1\0" * 3840], CancelToken())
    flush(proc)
    assert [f["kind"] for f in proc._stdin.frames()] == ["speech_cancel", "speech_cancel"]


@pytest.mark.parametrize("windows", [True, False])
@pytest.mark.parametrize("mic_mode, policy, conversion, device_silenced, blocks_silenced, gate", [
    ("translated", "suppress", "off", True, False, True),
    ("translated", "suppress", "on", False, True, False),
    ("translated", "mix", "off", False, False, False),
    ("off", "suppress", "on", False, False, False),
])
def test_who_silences_the_direct_voice(monkeypatch, controller_module, windows, mic_mode, policy, conversion,
                                       device_silenced, blocks_silenced, gate):
    module = controller_module
    calls = {}
    app = module.Controller.__new__(module.Controller)
    app.direct_voice = SimpleNamespace(set_suppressed=lambda v: calls.update(device=v),
                                       set_direct_suppressed=lambda v: calls.update(blocks=v))
    monkeypatch.setattr(module.Controller, "_directUsesOutputDevice", staticmethod(lambda: windows))
    settings = SimpleNamespace(mic_mode=mic_mode, direct_policy=policy, conversion=conversion)
    app._applyDirectPolicy(settings)
    # The device route silences the whole output; with speech through the conversion only
    # the microphone's blocks are silenced, on either route, and the Linux gate stays open.
    assert calls == {"device": device_silenced and windows, "blocks": blocks_silenced}
    assert module.Controller._gateSuppressesDirect(settings) is gate


class Bus:
    def __init__(self, available):
        self.played = []
        self._available = available

    def available(self):
        return self._available

    def play(self, frames, device, token, on_first_audio, monitor=None):
        self.played.append(("converted", list(frames), monitor))
        on_first_audio(1, 48000)


def run_bus(conversion, available):
    from models.tts.tts_scheduler import VoiceEventBus
    from models.voice_events import SpeechMessageEvent

    device = SimpleNamespace(played=[])

    def play(frames, dev, token, first, monitor=None):
        device.played.append((list(frames), monitor))
        first(1, 48000)

    class Provider:
        def __init__(self, url):
            pass

        def synthesize_stream(self, text, voice, language, token, **options):
            return iter([AudioFrame(b"\1\0" * 480, 48000)])

    converted = Bus(available)
    settings = VoiceSettings(mode="original", output_device="cable", japanese_server="external",
                             conversion=conversion)
    bus = VoiceEventBus(settings, provider_factory=Provider, router=SimpleNamespace(play=play),
                        converted_router=converted, monitor_factory=None)
    event = SpeechMessageEvent(event_id="e1", source="chat", original_text="こんにちは", translated_text=None,
                               source_language="Japanese", target_language=None, timestamp_ns=time.monotonic_ns())
    assert bus.publish(event)
    for _ in range(200):
        if bus.status()["completed"] or bus.status()["errors"]:
            break
        time.sleep(.01)
    bus.close()
    return device.played, converted.played


def test_tts_goes_through_the_conversion_only_when_asked_and_when_one_runs():
    device, converted = run_bus("on", True)
    assert device == [] and len(converted) == 1 and converted[0][2] is None
    device, converted = run_bus("on", False)
    assert len(device) == 1 and converted == []
    device, converted = run_bus("off", True)
    assert len(device) == 1 and converted == []
