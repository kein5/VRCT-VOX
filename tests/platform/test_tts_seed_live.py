"""Opt-in CPU reproducibility using an existing, consented Irodori model only."""
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS
from tools.live_tts_acceptance import SpeechServer


@pytest.mark.skipif(os.environ.get('VRCT_TEST_TTS_SEED') != '1', reason='opt-in existing Irodori CPU model')
def test_same_seed_and_instruction_reproduce_cpu_pcm(tmp_path):
    model = Path(os.environ['VRCT_TEST_SPEECH_MODEL']).resolve(strict=True)
    binary = Path(os.environ['VRCT_TEST_SPEECH_BINARY']).resolve(strict=True)
    server = SpeechServer(SimpleNamespace(model=model, speech_binary=str(binary), device='CPU', output=tmp_path))
    report = dict(status='failed', device='CPU', seed=42, repetitions=2,
                  physical_capture=False, vrchat=False, perceptual_quality=False, requests=[])
    try:
        server.start()
        provider = SpeechCppTTS(server.url)
        outputs = []
        for index in range(2):
            started = time.monotonic()
            frames = list(provider.synthesize_stream('こんにちは。', 'none', 'ja',
                          CancelToken(), seed=42, instructions='落ち着いた声で、自然に話してください。'))
            assert frames and all(frame.sample_rate == 48000 and frame.channels == 1 for frame in frames)
            pcm = b''.join(frame.pcm for frame in frames)
            assert pcm and any(pcm)
            outputs.append(pcm)
            (tmp_path / f'cpu-seed42-{index}.pcm').write_bytes(pcm)
            report['requests'].append(dict(seconds=time.monotonic() - started, bytes=len(pcm),
                                           sha256=hashlib.sha256(pcm).hexdigest()))
        assert outputs[0] == outputs[1]
        report['status'] = 'passed'
    finally:
        server.stop()
        (tmp_path / 'seed-reproducibility.json').write_text(json.dumps(report, indent=2))
