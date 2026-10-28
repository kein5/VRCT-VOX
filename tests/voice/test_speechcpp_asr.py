"""HTTP-level speech.cpp contract; tests neither record nor download audio."""
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import io
import json
from threading import Event, Thread, Timer
import time
from types import SimpleNamespace
import wave

import pytest

from models.tts.speechcpp_tts import CancelToken
from models.voice_events import AudioFrame


def module():
    return importlib.import_module('models.transcription.speechcpp_asr')


@contextmanager
def server():
    state = SimpleNamespace(models={'data': [
        {'id': 'tts', 'speech': {'task': 'synthesis'}},
        {'id': 'asr', 'speech': {'task': 'recognition', 'languages': ['ja'],
                              'options': [{'name': 'language'}]}},
    ]}, posts=[], get_count=0, status=200, payload=b'{"text":"private text"}',
        stop='complete', stall=None, release=Event(), entered=Event())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state.get_count += 1
            assert self.path == '/v1/models'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            body = json.dumps(state.models).encode()
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            assert self.path == '/v1/audio/transcriptions'
            body = self.rfile.read(int(self.headers['Content-Length']))
            message = BytesParser(policy=default).parsebytes(
                ('Content-Type: ' + self.headers['Content-Type'] + '\r\n\r\n').encode() + body)
            parts = {p.get_param('name', header='content-disposition'): p.get_payload(decode=True)
                     for p in message.iter_parts()}
            state.posts.append(parts)
            state.entered.set()
            if state.stall == 'headers':
                state.release.wait(3)
                return
            self.send_response(state.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('X-Speech-Stop', state.stop)
            if state.status == 302:
                self.send_header('Location', '/redirect-must-not-follow')
            self.send_header('Content-Length', str(len(state.payload)))
            self.end_headers()
            try:
                if state.stall == 'body':
                    while not state.release.wait(.02):
                        self.wfile.write(b' ')
                        self.wfile.flush()
                else:
                    self.wfile.write(state.payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=lambda: http.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}', state
    finally:
        state.release.set()
        http.shutdown()
        http.server_close()
        thread.join(2)


@pytest.mark.parametrize('url', ['https://example.com', 'http://192.168.1.2',
    'http://user:pw@127.0.0.1', 'http://127.0.0.1/v1', 'http://localhost?x=y'])
def test_audio_cannot_be_configured_for_remote_or_credentialed_url(url):
    with pytest.raises(ValueError):
        module().SpeechCppASR(url)


def test_discovery_and_multipart_preserve_stereo_samples_and_rate(monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    with server() as (url, state):
        client = module().SpeechCppASR(url)
        assert [m.id for m in client.recognizers()] == ['asr']
        audio = AudioFrame(b'\1\0\2\0' * 64, 44100, 2)
        result = client.transcribe(audio, 'asr', 'ja')
        assert (result.text, result.model, result.requested_language) == ('private text', 'asr', 'ja')
        assert len(state.posts) == 1
        parts = state.posts[0]
        assert set(parts) == {'file', 'model', 'language', 'response_format'}
        assert parts['response_format'] == b'json' and parts['model'] == b'asr'
        with wave.open(io.BytesIO(parts['file']), 'rb') as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (44100, 2, 2)
            assert wav.readframes(wav.getnframes()) == audio.pcm


@pytest.mark.parametrize('model,language', [('missing', 'ja'), ('tts', 'ja'), ('asr', 'en')])
def test_incompatible_model_or_language_sends_no_audio(model, language):
    with server() as (url, state):
        with pytest.raises(module().ASRError):
            module().SpeechCppASR(url).transcribe(AudioFrame(b'\0\0', 16000), model, language)
        assert state.posts == []


def test_rechecks_model_task_after_previous_success():
    with server() as (url, state):
        client = module().SpeechCppASR(url)
        client.transcribe(AudioFrame(b'\0\0', 16000), 'asr')
        state.models['data'][1]['speech']['task'] = 'synthesis'
        with pytest.raises(module().ASRError):
            client.transcribe(AudioFrame(b'\0\0', 16000), 'asr')
        assert len(state.posts) == 1


@pytest.mark.parametrize('payload', [b'not json', b'{"text":4}', b'[]', b'{"other":"private"}', b' ' * (1024 * 1024 + 1)])
def test_bad_or_large_response_never_becomes_transcript(payload):
    with server() as (url, state):
        state.payload = payload
        with pytest.raises(module().ASRError) as caught:
            module().SpeechCppASR(url).transcribe(AudioFrame(b'\0\0', 16000), 'asr')
        assert 'private' not in str(caught.value)


@pytest.mark.parametrize('status,stop', [(302, 'complete'), (400, 'complete'), (200, 'model_limit'), (200, '')])
def test_errors_redirects_and_truncated_recognition_do_not_return_final(status, stop):
    with server() as (url, state):
        state.status, state.stop = status, stop
        with pytest.raises(module().ASRError) as caught:
            module().SpeechCppASR(url).transcribe(AudioFrame(b'\0\0', 16000), 'asr')
        assert 'private' not in str(caught.value)
        assert state.get_count == 1 and len(state.posts) == 1


def test_empty_recognition_is_valid_without_inventing_confidence():
    with server() as (url, state):
        state.payload = b'{"text":""}'
        result = module().SpeechCppASR(url).transcribe(AudioFrame(b'\0\0', 16000), 'asr')
        assert result.text == ''
        assert not hasattr(result, 'confidence')


@pytest.mark.parametrize('stage', ['headers', 'body'])
@pytest.mark.parametrize('cancel', [False, True])
def test_total_deadline_and_cancel_interrupt_header_or_trickle_wait(stage, cancel):
    with server() as (url, state):
        state.stall = stage
        # Larger than any amount delivered before timeout.
        state.payload = b' ' * 5000
        token = CancelToken()
        timer = Timer(.15, token.cancel)
        if cancel:
            timer.start()
        started = time.monotonic()
        try:
            with pytest.raises(module().ASRError, match='cancelled' if cancel else 'timeout'):
                module().SpeechCppASR(url, timeout=2 if cancel else .15).transcribe(
                    AudioFrame(b'\0\0', 16000), 'asr', cancel_token=token)
        finally:
            timer.cancel()
        assert time.monotonic() - started < .8
        assert state.entered.is_set()


@pytest.mark.parametrize('audio', [AudioFrame(b'', 16000), AudioFrame(b'\0\0' * (16000 * 60 + 1), 16000)])
def test_empty_or_overlong_audio_does_not_open_connection(audio):
    with pytest.raises(module().ASRError, match='invalid_audio'):
        module().SpeechCppASR('http://127.0.0.1:1').transcribe(audio, 'asr')


def test_file_cli_writes_metrics_without_transcript_and_refuses_overwrite(tmp_path, monkeypatch):
    command = importlib.import_module('tools.speechcpp_asr_poc')
    source, report = tmp_path / 'input.wav', tmp_path / 'report.json'
    with wave.open(str(source), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\1\0' * 160)
    with server() as (url, state):
        monkeypatch.setattr('sys.argv', ['asr-poc', '--url', url, '--model', 'asr',
            '--input', str(source), '--report', str(report)])
        assert command.main() == 0
        value = json.loads(report.read_text())
        assert value['characters'] == len('private text') and value['duration_s'] == .01
        assert 'private text' not in report.read_text()
        with pytest.raises(FileExistsError):
            command.main()
        assert len(state.posts) == 1
