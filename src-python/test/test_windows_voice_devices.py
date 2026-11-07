"""Windows device list, playback and capture against a stand-in for PyAudioWPatch."""
import json
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from models.audio_routing import devices_windows as dw
from models.audio_routing import windows_route as wr
from models.audio_routing.source_bridge import Endpoint
from models.transcription import capture_windows as cw
from models.tts.speechcpp_tts import CancelToken, SpeechError

WASAPI = 2
MIC = dict(index=0, name='Mic (USB)', hostApi=WASAPI, maxInputChannels=2, maxOutputChannels=0,
           defaultSampleRate=44100.0)
SPEAKER = dict(index=1, name='Speakers (Sound)', hostApi=WASAPI, maxInputChannels=0, maxOutputChannels=2,
               defaultSampleRate=48000.0)
LOOPBACK = dict(index=2, name='Speakers (Sound) [Loopback]', hostApi=WASAPI, maxInputChannels=2,
                maxOutputChannels=0, defaultSampleRate=48000.0, isLoopbackDevice=True)
MME_MIC = dict(index=3, name='Mic (USB)', hostApi=0, maxInputChannels=2, maxOutputChannels=0,
               defaultSampleRate=44100.0)
HOSTS = {0: 'MME', WASAPI: 'Windows WASAPI'}


def identity(info):
    return json.dumps([HOSTS[info['hostApi']], info['name']], ensure_ascii=False)


class FakeStream:
    def __init__(self, owner, kwargs):
        self.owner, self.kwargs = owner, kwargs
        self.written = []
        self.active = True

    def write(self, pcm, exception_on_underflow=True):
        self.written.append(pcm)
        if self.owner.write_error:
            raise OSError('device gone')

    def is_active(self):
        return self.active

    def stop_stream(self):
        self.active = False

    def close(self):
        self.active = False


class FakePyAudio:
    def __init__(self, devices=(MIC, SPEAKER, LOOPBACK, MME_MIC)):
        self.devices = list(devices)
        self.streams = []
        self.rejected_rates = set()
        self.write_error = False

    def __call__(self):
        return self

    paInt16, paWASAPI, paContinue = 8, 13, 0

    @property
    def PyAudio(self):
        return self

    def terminate(self):
        pass

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, index):
        return self.devices[index]

    def get_host_api_info_by_index(self, index):
        return dict(name=HOSTS[index])

    def get_host_api_info_by_type(self, kind):
        return dict(index=WASAPI, defaultInputDevice=0, defaultOutputDevice=1)

    def get_wasapi_loopback_analogue_by_dict(self, info):
        return LOOPBACK

    def open(self, **kwargs):
        if kwargs['rate'] in self.rejected_rates:
            raise OSError('Invalid sample rate')
        stream = FakeStream(self, kwargs)
        self.streams.append(stream)
        return stream


@pytest.fixture
def audio(monkeypatch):
    fake = FakePyAudio()
    monkeypatch.setitem(sys.modules, 'pyaudiowpatch', fake)
    monkeypatch.setattr(dw, 'prepare_audio_thread', lambda: None)
    monkeypatch.setattr(cw, 'prepare_audio_thread', lambda: None)
    return fake


def mic_endpoint():
    return dw._endpoint(identity(MIC), 'mic')


def speaker_endpoint():
    return dw._endpoint(identity(SPEAKER), 'speaker')


def test_portaudio_is_only_touched_under_the_shared_lock(audio, monkeypatch):
    """Setting PortAudio up on two threads at once crashed the sidecar during startup."""
    held = []
    real_init = FakePyAudio.__call__

    def noted(self):
        held.append(dw.pyaudio_op_lock.locked())
        return real_init(self)

    monkeypatch.setattr(FakePyAudio, '__call__', noted)
    dw.enumerate_outputs()
    dw.enumerate_endpoints('mic')
    dw.default_endpoint('speaker')
    output = dw.WindowsOutput(identity(SPEAKER), 48000, 1)
    output.close(drain=True, token=CancelToken())
    assert held and all(held)
    assert not dw.pyaudio_op_lock.locked()


def test_endpoints_list_each_device_once_and_keep_a_stable_identity(audio):
    mics = dw.enumerate_endpoints('mic')
    assert [row['label'] for row in mics] == ['Mic (USB)']
    assert mics[0]['endpoint'] == dw.enumerate_endpoints('mic')[0]['endpoint']
    assert mics[0]['endpoint'].media_class == 'Audio/Source'
    speakers = dw.enumerate_endpoints('speaker')
    assert [row['label'] for row in speakers] == ['Speakers (Sound)']
    assert speakers[0]['endpoint'].media_class == 'Audio/Sink'


def test_default_endpoint_follows_wasapi_and_refuses_a_cable_as_microphone(audio):
    assert dw.default_endpoint('mic') == mic_endpoint()
    assert dw.default_endpoint('speaker') == speaker_endpoint()
    audio.devices[0] = dict(MIC, name='CABLE Output (VB-Audio Virtual Cable)')
    with pytest.raises(ValueError, match='realtime_default_endpoint_feedback'):
        dw.default_endpoint('mic')


def test_speaker_capture_opens_the_loopback_twin(audio):
    assert dw.capture_device(audio, audio, speaker_endpoint(), 'speaker') is LOOPBACK
    assert dw.capture_device(audio, audio, mic_endpoint(), 'mic') is MIC
    with pytest.raises(LookupError):
        dw.capture_device(audio, audio, Endpoint(1, 0, '["Windows WASAPI", "Gone"]', 'Audio/Source'), 'mic')


@pytest.mark.parametrize('first,second,expected', [
    ('["Windows WASAPI", "CABLE Output (VB-Audio Virtual Cable)"]',
     '["Windows WASAPI", "CABLE Input (VB-Audio Virtual Cable)"]', True),
    ('["MME", "CABLE Output (VB-Audio Virtual C"]', '["Windows WASAPI", "CABLE Input (VB-Audio Virtual Cable)"]', True),
    ('["Windows WASAPI", "Microphone (Steam Streaming Microphone)"]',
     '["Windows WASAPI", "Speakers (Steam Streaming Microphone)"]', True),
    ('["Windows WASAPI", "Microphone (Realtek Audio)"]', '["Windows WASAPI", "Speakers (Realtek Audio)"]', False),
    ('["Windows WASAPI", "Microphone (Realtek Audio)"]',
     '["Windows WASAPI", "CABLE Input (VB-Audio Virtual Cable)"]', False),
])
def test_only_two_ends_of_one_virtual_cable_count_as_feedback(first, second, expected):
    assert dw.same_virtual_cable(first, second) is expected


def test_mono_speech_is_written_as_stereo(audio):
    """A mono WASAPI stream garbled playback; both channels must carry the same samples."""
    output = dw.WindowsOutput(identity(SPEAKER), 48000, 1)
    assert audio.streams[0].kwargs['channels'] == 2
    output.write(np.array([1, -2, 3], '<i2').tobytes(), CancelToken())
    assert np.frombuffer(audio.streams[0].written[0], '<i2').tolist() == [1, 1, -2, -2, 3, 3]


def test_a_rate_the_device_refuses_is_converted_to_its_own(audio):
    audio.rejected_rates.add(24000)
    output = dw.WindowsOutput(identity(SPEAKER), 24000, 1)
    assert audio.streams[0].kwargs['rate'] == 48000
    tone = (np.sin(np.arange(24000) * 2 * np.pi * 440 / 24000) * 8000).astype('<i2').tobytes()
    for offset in range(0, len(tone), 480):
        output.write(tone[offset:offset + 480], CancelToken())
    written = np.frombuffer(b''.join(audio.streams[0].written), '<i2').reshape(-1, 2)
    assert abs(len(written) - 48000) < 2000  # About one second, minus the filter's delay.
    spectrum = np.abs(np.fft.rfft(written[:, 0].astype(float)))
    assert abs(np.argmax(spectrum) * 48000 / len(written) - 440) < 2


def test_builder_makes_exact_frames_with_stamps_behind_the_clock():
    builder = cw.FrameBuilder(48000, 2)
    stereo = np.repeat(np.arange(4800, dtype='<i2'), 2).tobytes()  # 100 ms.
    received = 10_000_000_000
    frames = builder.feed(stereo, received)
    assert len(frames) == 5
    assert all(len(f.audio.pcm) == cw.FRAME_BYTES and f.audio.sample_rate == 48000 for f in frames)
    stamps = [f.captured_ns for f in frames]
    assert stamps == sorted(set(stamps))
    # The clock reads up to one tick low; the newest frame's start must still be in its past.
    assert stamps[-1] <= received - 20_000_000 - cw._CLOCK_TICK_NS
    assert np.frombuffer(frames[0].audio.pcm, '<i2')[:3].tolist() == [0, 1, 2]


def test_builder_resamples_and_mixes_to_48k_mono():
    builder = cw.FrameBuilder(44100, 1)
    tone = (np.sin(np.arange(44100) * 2 * np.pi * 300 / 44100) * 8000).astype('<i2').tobytes()
    frames = []
    for offset in range(0, len(tone), 882):
        frames += builder.feed(tone[offset:offset + 882], 10_000_000_000 + offset * 1000)
    audio = np.frombuffer(b''.join(f.audio.pcm for f in frames), '<i2').astype(float)
    assert abs(len(audio) - 48000) < 3000
    assert abs(np.argmax(np.abs(np.fft.rfft(audio))) * 48000 / len(audio) - 300) < 2


class ScriptedCapture(cw.WindowsCapture):
    """Runs _pump against a fake stream without PortAudio's callback thread."""
    def run(self, stream, buffers, builder):
        self._pump(stream, buffers, builder)


def test_an_idle_loopback_fills_the_gap_with_silence(audio):
    frames = []

    def received(frame):
        frames.append(frame)
        if len(frames) >= 5:
            capture.request_stop()
        return True

    capture = ScriptedCapture(speaker_endpoint(), 'speaker', received, lambda code: None)
    from queue import Queue
    capture.run(FakeStream(audio, {}), Queue(), cw.FrameBuilder(48000, 2))
    assert len(frames) >= 5 and not any(any(f.audio.pcm) for f in frames)


def test_a_microphone_that_stops_delivering_is_reported(audio, monkeypatch):
    monkeypatch.setattr(cw, '_STALL_NS', 50_000_000)
    capture = ScriptedCapture(mic_endpoint(), 'mic', lambda frame: True, lambda code: None)
    from queue import Queue
    with pytest.raises(cw.CaptureError, match='asr_capture_stalled'):
        capture.run(FakeStream(audio, {}), Queue(), cw.FrameBuilder(48000, 2))


def test_a_lost_stream_is_reported(audio):
    stream = FakeStream(audio, {})
    stream.active = False
    capture = ScriptedCapture(speaker_endpoint(), 'speaker', lambda frame: True, lambda code: None)
    from queue import Queue
    with pytest.raises(cw.CaptureError, match='asr_capture_stream_disconnected'):
        capture.run(stream, Queue(), cw.FrameBuilder(48000, 2))


def test_a_stream_that_cannot_open_fails_start_with_its_code(audio):
    audio.rejected_rates.add(44100)
    errors = []
    capture = cw.WindowsCapture(mic_endpoint(), 'mic', lambda frame: True, errors.append)
    with pytest.raises(cw.CaptureError, match='asr_capture_stream_create_failed'):
        capture.start()
    assert errors == ['asr_capture_stream_create_failed']


def test_queued_output_never_blocks_the_caller_and_keeps_the_newest(audio):
    release = []

    class Stalled:
        def __init__(self, *args, **kwargs):
            self.written = []

        def write(self, pcm, token):
            while not release:
                time.sleep(.005)
            self.written.append(pcm)

        def close(self, *, drain, token):
            pass

    original = wr.WindowsOutput
    wr.WindowsOutput = Stalled
    try:
        output = wr.QueuedOutput('device')
        token = CancelToken()
        started = time.monotonic()
        for value in range(40):
            output.write(bytes([value]), token)
        assert time.monotonic() - started < .5
        release.append(True)
        deadline = time.monotonic() + 2
        while not output._queue.empty() and time.monotonic() < deadline:
            time.sleep(.01)
        assert output._output.written[-1] == bytes([39])
        output.close(drain=False, token=token)
    finally:
        wr.WindowsOutput = original


def test_a_failed_device_surfaces_on_the_next_write(audio):
    audio.write_error = True
    output = wr.QueuedOutput(identity(SPEAKER))
    token = CancelToken()
    output.write(b'\0\0', token)
    deadline = time.monotonic() + 2
    while not output._failed and time.monotonic() < deadline:
        time.sleep(.01)
    with pytest.raises(SpeechError, match='vc_output_failed'):
        output.write(b'\0\0', token)
    output.close(drain=False, token=token)


class RecordingOutput:
    def __init__(self):
        self.written = []

    def write(self, pcm, token):
        self.written.append(pcm)

    def close(self, *, drain, token):
        pass


def test_bridge_writes_silence_while_muted_and_voice_after_resume(monkeypatch):
    """Windows has no gate behind the device, so mute must be applied to the samples."""
    output = RecordingOutput()
    capture = SimpleNamespace(start=lambda: None, stop=lambda: None, request_stop=lambda: None)
    monkeypatch.setattr(wr, 'WindowsOutput', lambda *args, **kwargs: output)
    monkeypatch.setattr(wr, '_check_devices', lambda source, device: None)
    import models.transcription.capture_windows as module
    monkeypatch.setattr(module, 'WindowsCapture', lambda *args: capture)
    bridge = wr.WindowsBridge('device')
    bridge.set_monitor_muted(True)
    bridge.start(source=Endpoint(1, 0, 'mic', 'Audio/Source'))
    frame = SimpleNamespace(audio=SimpleNamespace(pcm=b'\x01\x02'))
    deadline = time.monotonic() + 2
    while not bridge.health()['active'] and time.monotonic() < deadline:
        time.sleep(.01)
    assert bridge._audio(frame)
    while not output.written and time.monotonic() < deadline:
        time.sleep(.01)
    assert output.written[0] == b'\0\0'
    bridge.set_monitor_muted(False)
    assert bridge._audio(frame)
    while len(output.written) < 2 and time.monotonic() < deadline:
        time.sleep(.01)
    assert output.written[1] == b'\x01\x02'
    assert bridge.close(timeout=2)
    state = bridge.health()
    assert not state['requested'] and not state['active'] and state['error'] is None


def test_bridge_reports_a_cable_looped_onto_itself(monkeypatch):
    monkeypatch.setattr(wr, 'enumerate_outputs', lambda: [{'id': '["Windows WASAPI", "CABLE Input (VB-Audio Virtual Cable)"]'}])
    bridge = wr.WindowsBridge('["Windows WASAPI", "CABLE Input (VB-Audio Virtual Cable)"]')
    bridge.start(source=Endpoint(1, 0, '["Windows WASAPI", "CABLE Output (VB-Audio Virtual Cable)"]', 'Audio/Source'))
    deadline = time.monotonic() + 2
    while bridge.health()['error'] is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert bridge.health()['error'] == 'vc_feedback_blocked'
    assert bridge.close(timeout=2)
