"""Optional real-runtime test: use the documented Linux Python environment."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or importlib.util.find_spec("faster_whisper") is None,
    reason="requires the optional Linux runtime dependencies",
)


def test_window_image_processing_imports_without_windows_callback_abi(tmp_path):
    program = '''
from models.overlay.window_capture import bgraFromCapture
pixels = bgraFromCapture((bytes([1, 2, 3, 4, 5, 6, 7, 8]), (2, 1), (1, 0, 2, 1)))
assert pixels.tolist() == [[[5, 6, 7, 8]]]
print("portable-image-ok")
'''
    result = subprocess.run([sys.executable, "-c", program], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ROOT / "src-python")),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "portable-image-ok" in result.stdout


def test_speaker_pcm_processing_does_not_require_windows_audio_driver(tmp_path):
    # Deleting the portability fix makes this fail on the real import. Keeping
    # the import but corrupting sample width/rate also fails the PCM assertions.
    program = '''
import struct
from models.transcription.transcription_transcriber import AudioTranscriber
class Source:
    SAMPLE_RATE = 24000
    SAMPLE_WIDTH = 2
    channels = 1
transcriber = AudioTranscriber(True, Source(), 3, 10, "Google")
pcm = struct.pack("<hhhh", 1000, -2000, 32767, -32768)
transcriber.audio_sources["last_sample"] = pcm
audio = transcriber.processSpeakerData()
assert audio.sample_rate == 24000
assert audio.sample_width == 2
assert audio.get_raw_data() == pcm
print("portable-pcm-ok")
'''
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src-python"),
               HF_HOME=str(tmp_path / "hf"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    result = subprocess.run([sys.executable, "-c", program], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "portable-pcm-ok" in result.stdout
