"""Real child stderr/exit handling, with no audio device or model."""
import sys

import pytest

from models.audio_routing.source_bridge import Endpoint

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="PipeWire helper")


@pytest.mark.parametrize("code", ["latency_changed", "clock_invalid", None])
def test_native_capture_fixed_error_survives_noisy_fragmented_stderr(
    tmp_path, monkeypatch, code
):
    from models.transcription import capture_pipewire as m

    helper = tmp_path / "fake-capture"
    # The long unknown line ends with a valid-looking suffix: never accept it.
    body = "import os, time\nos.write(2, b'private' * 12000 + b'asr_capture_stalled\\n')\n"
    if code:
        body += f"os.write(2, b'asr_capture_'); time.sleep(.01); os.write(2, {code.encode()!r} + b'\\n')\n"
    helper.write_text(f"#!{sys.executable}\n" + body)
    helper.chmod(0o700)
    endpoint = Endpoint(1, 2, "synthetic", "Audio/Source")
    monkeypatch.setattr(m, "_read_graph", lambda: [])
    monkeypatch.setattr(m, "_select", lambda *args: endpoint)
    frames, errors = [], []
    capture = m.PipeWireCapture(endpoint, "mic", frames.append, errors.append, helper=helper)
    expected = "asr_capture_" + code if code else "asr_capture_helper_closed"
    try:
        with pytest.raises(m.CaptureError, match=f"^{expected}$"):
            capture.start()
        assert frames == [] and errors == [expected]
        assert capture._process.poll() is not None
    finally:
        capture.stop()


def test_capture_start_timeout_reaps_silent_helper(tmp_path, monkeypatch):
    from models.transcription import capture_pipewire as m

    helper = tmp_path / "silent-capture"
    helper.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    helper.chmod(0o700)
    endpoint = Endpoint(1, 2, "synthetic", "Audio/Source")
    monkeypatch.setattr(m, "_read_graph", lambda: [])
    monkeypatch.setattr(m, "_select", lambda *args: endpoint)
    errors = []
    capture = m.PipeWireCapture(endpoint, "mic", lambda frame: True, errors.append, helper=helper)
    wait = capture._ready.wait
    monkeypatch.setattr(capture._ready, "wait", lambda timeout: wait(.1))
    with pytest.raises(m.CaptureError, match="^asr_capture_start_timeout$"):
        capture.start()
    assert capture._process.poll() is not None and errors == []
