"""Local speech.cpp REST recognition without OpenAI SDK parameter defaults."""
from dataclasses import dataclass
import errno
import http.client
import io
import json
import math
import select
import socket
from threading import Event, Timer
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4
import wave

from models.tts.settings import local_url
from models.tts.speechcpp_tts import CancelToken
from models.voice_events import AudioFrame
from models.http_stream import InterruptibleSocket

MAX_RESPONSE = 1024 * 1024


class ASRError(Exception):
    """A fixed code only; server bodies, audio and text never appear here."""


@dataclass(frozen=True)
class RecognitionModel:
    id: str
    languages: tuple[str, ...]
    accepts_language: bool


@dataclass(frozen=True)
class ASRResult:
    text: str
    model: str
    requested_language: str  # Not a detected language or a confidence estimate.


class SpeechCppASR:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = local_url(base_url)
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError('Invalid ASR timeout')
        self.timeout = timeout

    def _request(self, method, path, token, deadline, body=None, headers=None):
        url = urlsplit(self.base_url)
        expired = Event()
        sock, response, timer = None, None, None

        def check():
            if token.is_set():
                raise ASRError('cancelled')
            if expired.is_set() or monotonic() >= deadline:
                raise ASRError('timeout')

        def interrupt():
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        def expire():
            expired.set()
            interrupt()

        check()
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=max(.001, deadline - monotonic()))
        try:
            timer = Timer(max(0, deadline - monotonic()), expire)
            timer.daemon = True
            timer.start()
            # Own a nonblocking numeric-loopback socket before connecting.
            # Timeout-mode connect can hide cancellation inside the OS wait.
            sock = socket.socket(socket.AF_INET6 if ':' in url.hostname else socket.AF_INET,
                                 socket.SOCK_STREAM)
            conn.sock = sock
            sock.setblocking(False)
            token.register(interrupt)
            check()
            error = sock.connect_ex((url.hostname, url.port))
            pending = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EINTR,
                       getattr(errno, 'WSAEWOULDBLOCK', errno.EWOULDBLOCK)}
            if error in pending:
                while True:
                    check()
                    # Winsock reports failed connects in exceptfds; Linux can
                    # report success or failure as writable. Inspect SO_ERROR.
                    _, writable, exceptional = select.select(
                        [], [sock], [sock], max(0, min(.02, deadline - monotonic())))
                    check()
                    if writable or exceptional:
                        error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        break
            if error not in (0, errno.EISCONN):
                raise OSError(error, 'connect_failed')
            check()
            sock.settimeout(max(.001, deadline - monotonic()))
            sock = conn.sock = InterruptibleSocket(sock)
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            check()
            if response.status != 200:
                raise ASRError(f'http_{response.status}')
            content_type = response.getheader('Content-Type', '').split(';')[0].strip().lower()
            if content_type != 'application/json':
                raise ASRError('expected_json')
            if response.length is not None and response.length > MAX_RESPONSE:
                raise ASRError('response_too_large')
            payload = bytearray()
            while True:
                check()
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(payload)))
                check()
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_RESPONSE:
                    raise ASRError('response_too_large')
            if response.length not in (None, 0):
                raise ASRError('truncated_response')
            try:
                value = json.loads(payload)
            except (ValueError, UnicodeError):
                raise ASRError('invalid_json') from None
            check()
            return value, response.getheader('X-Speech-Stop')
        except (OSError, http.client.HTTPException):
            check()
            raise ASRError('transport_error') from None
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            if response is not None:
                response.close()
            conn.close()

    def _recognizers(self, token, deadline):
        payload, _ = self._request('GET', '/v1/models', token, deadline)
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
            raise ASRError('invalid_models')
        models, ids = [], set()
        for row in payload['data']:
            if not isinstance(row, dict) or not isinstance(row.get('speech'), dict):
                raise ASRError('invalid_models')
            speech = row['speech']
            if speech.get('task') != 'recognition':
                continue
            name, languages = row.get('id'), speech.get('languages')
            options = speech.get('options')
            if (not isinstance(name, str) or not name.strip() or len(name) > 200
                    or any(ord(c) < 32 for c in name) or name in ids
                    or not isinstance(languages, list) or not all(isinstance(v, str) for v in languages)
                    or not isinstance(options, list) or not all(isinstance(v, dict) for v in options)):
                raise ASRError('invalid_models')
            ids.add(name)
            models.append(RecognitionModel(name, tuple(languages), any(v.get('name') == 'language' for v in options)))
        return tuple(models)

    def recognizers(self, cancel_token=None):
        return self._recognizers(cancel_token or CancelToken(), monotonic() + self.timeout)

    def transcribe(self, audio: AudioFrame, model: str, language='auto', cancel_token=None):
        deadline = monotonic() + self.timeout
        token = cancel_token or CancelToken()
        if (not isinstance(audio, AudioFrame) or not audio.pcm
                or len(audio.pcm) > audio.sample_rate * audio.channels * 2 * 60
                or len(audio.pcm) > 24 * 1024 * 1024):
            raise ASRError('invalid_audio')
        available = self._recognizers(token, deadline)
        selected = next((m for m in available if m.id == model), None)
        if selected is None:
            raise ASRError('model_unavailable')
        if language != 'auto' and (not selected.accepts_language or language not in selected.languages):
            raise ASRError('unsupported_language')
        wav = io.BytesIO()
        with wave.open(wav, 'wb') as stream:
            stream.setparams((audio.channels, 2, audio.sample_rate, 0, 'NONE', 'not compressed'))
            stream.writeframes(audio.pcm)
        boundary = uuid4().hex
        fields = {'model': selected.id, 'response_format': 'json'}
        if selected.accepts_language:
            fields['language'] = language
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
                 for key, value in fields.items()]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
                     + wav.getvalue() + b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        value, stop = self._request('POST', '/v1/audio/transcriptions', token, deadline,
            b''.join(parts), {'Content-Type': 'multipart/form-data; boundary=' + boundary})
        if stop != 'complete':
            raise ASRError('incomplete_recognition')
        if not isinstance(value, dict) or not isinstance(value.get('text'), str):
            raise ASRError('invalid_transcript')
        return ASRResult(value['text'], selected.id, language)
