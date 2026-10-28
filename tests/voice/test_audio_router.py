import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.audio_routing.devices_windows import WindowsOutput
from models.tts.speechcpp_tts import CancelToken, SpeechError
from models.voice_events import AudioFrame


@pytest.mark.parametrize("rate,channels", [(24000, 1), (44100, 1), (48000, 1), (48000, 2)])
def test_router_preserves_format_and_bounds_writes(rate, channels):
    sink = MagicMock()
    factory = MagicMock(return_value=sink)
    first = MagicMock()
    pcm = b"\x01\x00" * rate * channels
    AudioRouter(factory).play(iter([AudioFrame(pcm, rate, channels)]), "cable", CancelToken(), first)
    factory.assert_called_once_with("cable", rate, channels)
    assert b"".join(c.args[0] for c in sink.write.call_args_list) == pcm
    assert all(len(c.args[0]) <= rate // 100 * 2 * channels for c in sink.write.call_args_list)
    assert first.call_count == 1
    assert sink.close.call_args.kwargs["drain"] is True


def test_cancel_discards_rest_and_releases_output():
    token = CancelToken()
    sink = MagicMock()
    sink.write.side_effect = lambda pcm, _: token.cancel()
    frames = iter([AudioFrame(b"\x01\x00" * 48000, 48000)])
    with pytest.raises(SpeechError, match="cancelled"):
        AudioRouter(lambda *args: sink).play(frames, "cable", token, lambda *args: None)
    assert sink.write.call_count == 1
    assert sink.close.call_args.kwargs["drain"] is False


def test_silence_does_not_count_as_first_audio():
    first = MagicMock()
    AudioRouter(lambda *args: MagicMock()).play(iter([AudioFrame(bytes(960), 48000)]), "cable", CancelToken(), first)
    first.assert_not_called()


def test_first_nonzero_write_remains_subject_to_deadline_while_waiting(monkeypatch):
    from models.tts import speechcpp_tts as tokens
    clock = [1.0]
    monkeypatch.setattr(tokens, 'monotonic', lambda: clock[0])
    token = CancelToken(start_deadline=2.0)
    written = []
    def write(pcm, guard):
        if any(pcm):
            clock[0] = 2.1  # Output readiness arrives after the startup deadline.
        guard.check()
        written.append(pcm)
    sink = MagicMock()
    sink.write.side_effect = write
    frames = [AudioFrame(bytes(960) + b'\1\0' * 480, 48000)]
    with pytest.raises(SpeechError, match='speech_expired'):
        AudioRouter(lambda *args: sink).play(frames, 'test', token, MagicMock())
    assert written == [bytes(960)]
    assert sink.close.call_args.kwargs['drain'] is False


def test_successful_nonblocking_audio_write_commits_start_before_expiry(monkeypatch):
    from models.tts import speechcpp_tts as tokens
    clock = [1.0]
    monkeypatch.setattr(tokens, 'monotonic', lambda: clock[0])
    token = CancelToken(start_deadline=2.0)
    written = []
    def write():
        written.append(b'\1\0')
        return 2
    assert token.commit_audio_write(b'\1\0', write) == 2
    clock[0] = 3.0
    token.check()
    assert not token.is_set() and written == [b'\1\0']


def test_failed_or_silent_nonblocking_write_does_not_disable_expiry(monkeypatch):
    from models.tts import speechcpp_tts as tokens
    clock = [1.0]
    monkeypatch.setattr(tokens, 'monotonic', lambda: clock[0])
    for pcm, writer in [(b'\1\0', lambda: (_ for _ in ()).throw(BlockingIOError())),
                        (b'\0\0', lambda: 2)]:
        token = CancelToken(start_deadline=2.0)
        try:
            token.commit_audio_write(pcm, writer)
        except BlockingIOError:
            pass
        clock[0] = 2.1
        with pytest.raises(SpeechError, match='speech_expired'):
            token.check()
        clock[0] = 1.0


def test_format_change_and_write_failure_release_device():
    sink = MagicMock()
    frames = iter([AudioFrame(b"\x01\x00", 48000), AudioFrame(b"\x01\x00", 24000)])
    with pytest.raises(SpeechError, match="format_changed"):
        AudioRouter(lambda *args: sink).play(frames, "cable", CancelToken(), lambda *args: None)
    assert sink.close.call_args.kwargs["drain"] is False
    sink.write.side_effect = OSError("device removed")
    with pytest.raises(OSError):
        AudioRouter(lambda *args: sink).play(iter([AudioFrame(b"\x01\x00", 48000)]), "cable", CancelToken(), lambda *args: None)
    assert sink.close.call_count == 2


def test_windows_explicit_device_rate_and_normal_drain(monkeypatch):
    pa = MagicMock()
    pa.get_device_count.return_value = 2
    pa.get_device_info_by_index.side_effect = lambda i: {"hostApi": 0, "name": ["speakers", "virtual cable"][i], "maxOutputChannels": 2}
    pa.get_host_api_info_by_index.return_value = {"name": "WASAPI"}
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(PyAudio=lambda: pa, paInt16=8))
    output = WindowsOutput(json.dumps(["WASAPI", "virtual cable"]), 44100, 1)
    assert pa.open.call_args.kwargs["output_device_index"] == 1
    assert pa.open.call_args.kwargs["rate"] == 44100
    output.close(drain=True, token=CancelToken())
    pa.open.return_value.stop_stream.assert_called_once()
    pa.open.return_value.close.assert_called_once()
    pa.terminate.assert_called_once()


def test_windows_removed_device_never_falls_back(monkeypatch):
    pa = MagicMock()
    pa.get_device_count.return_value = 0
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(PyAudio=lambda: pa, paInt16=8))
    with pytest.raises(SpeechError, match="output_missing"):
        WindowsOutput("old-device-id", 48000, 1)
    pa.open.assert_not_called()
    pa.terminate.assert_called_once()


@pytest.mark.skipif(sys.platform == "win32", reason="PipeWire adapter is Linux-only")
def test_pipewire_target_not_found_never_starts_default(monkeypatch):
    from models.audio_routing import devices_pipewire as pw
    monkeypatch.setattr(pw, "enumerate_outputs", lambda: [])
    start = MagicMock()
    monkeypatch.setattr(pw.subprocess, "Popen", start)
    with pytest.raises(SpeechError, match="output_missing"):
        pw.PipeWireOutput("missing-sink", 48000, 1)
    start.assert_not_called()


@pytest.mark.skipif(sys.platform == "win32", reason="PipeWire adapter is Linux-only")
def test_pipewire_process_contract_and_release(monkeypatch):
    import os
    from models.audio_routing import devices_pipewire as pw
    read_fd, write_fd = os.pipe()
    pipe = os.fdopen(write_fd, "wb", buffering=0)
    process = MagicMock(stdin=pipe)
    process.poll.side_effect = [None, None, 0, 0]
    process.returncode = 0
    start = MagicMock(return_value=process)
    monkeypatch.setattr(pw, "enumerate_outputs", lambda: [{"id": "vrct.voice.sink"}])
    monkeypatch.setattr(pw.subprocess, "Popen", start)
    try:
        output = pw.PipeWireOutput("vrct.voice.sink", 24000, 1)
        args = start.call_args.args[0]
        assert args[args.index("--rate") + 1] == "24000"
        assert args[args.index("--target") + 1] == "vrct.voice.sink"
        assert "node.dont-fallback=true" in args[args.index("--properties") + 1]
        output.write(b"\x01\x00", CancelToken())
        assert os.read(read_fd, 2) == b"\x01\x00"
        output.close(drain=True, token=CancelToken())
        assert pipe.closed
    finally:
        os.close(read_fd)
        pipe.close()


@pytest.mark.skipif(sys.platform == "win32", reason="PipeWire adapter is Linux-only")
def test_pipewire_disappearing_consumer_reports_disconnect(monkeypatch):
    import os
    from models.audio_routing import devices_pipewire as pw
    read_fd, write_fd = os.pipe()
    os.close(read_fd)  # Consumer disappeared between poll and write.
    pipe = os.fdopen(write_fd, "wb", buffering=0)
    process = MagicMock(stdin=pipe)
    process.poll.return_value = None
    monkeypatch.setattr(pw, "enumerate_outputs", lambda: [{"id": "virtual"}])
    monkeypatch.setattr(pw.subprocess, "Popen", lambda *a, **kw: process)
    output = pw.PipeWireOutput("virtual", 48000, 1)
    try:
        with pytest.raises(SpeechError, match="output_disconnected"):
            output.write(b"\x01\x00", CancelToken())
    finally:
        output.close(drain=False, token=CancelToken())
    assert pipe.closed
    process.terminate.assert_called_once()
