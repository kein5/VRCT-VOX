"""Opt-in local installed recognizer; never fetch a model or capture audio."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import wave

import pytest

from models.transcription.speechcpp_asr import ASRError, SpeechCppASR
from models.voice_events import AudioFrame


@pytest.mark.skipif(not os.environ.get('VRCT_SPEECH_ASR_MODEL'), reason='existing consented local model/input required')
def test_installed_speechcpp_recognizer_and_cli(tmp_path):
    binary = Path(os.environ['VRCT_SPEECH_BINARY']).resolve(strict=True)
    model = Path(os.environ['VRCT_SPEECH_ASR_MODEL']).resolve(strict=True)
    source = Path(os.environ['VRCT_SPEECH_ASR_INPUT']).resolve(strict=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with (tmp_path / 'server.log').open('wb') as log:
        process = subprocess.Popen([str(binary), 'serve', str(model), '--host', '127.0.0.1',
                                    '--port', str(port), '--device', 'gpu'], stdout=log, stderr=log)
        try:
            client = SpeechCppASR(url)
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None, 'installed_server_exited'
                try:
                    models = client.recognizers()
                    break
                except ASRError:
                    assert time.monotonic() < deadline, 'installed_server_not_ready'
                    time.sleep(.05)
            assert len(models) == 1
            with wave.open(str(source), 'rb') as wav:
                assert wav.getsampwidth() == 2
                frame = AudioFrame(wav.readframes(wav.getnframes()), wav.getframerate(), wav.getnchannels())
            result = client.transcribe(frame, models[0].id, 'ja')
            assert isinstance(result.text, str) and result.text.strip()
            for name, language in [('missing-model', 'ja'), (models[0].id, 'unknown-language')]:
                with pytest.raises(ASRError):
                    client.transcribe(frame, name, language)
            report = tmp_path / 'metrics.json'
            call = subprocess.run([sys.executable, 'tools/speechcpp_asr_poc.py', '--url', url,
                '--model', models[0].id, '--language', 'ja', '--input', str(source), '--report', str(report)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
            assert call.returncode == 0, 'asr_cli_failed'
            metrics = json.loads(report.read_text())
            assert metrics['status'] == 'complete' and metrics['characters'] > 0
            assert result.text not in report.read_text()
            assert metrics['sample_rate'] == frame.sample_rate
        finally:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
    # Only two successful audio calls; the two preflight failures sent no WAV.
    assert (tmp_path / 'server.log').read_text().count('POST /v1/audio/transcriptions') == 2
