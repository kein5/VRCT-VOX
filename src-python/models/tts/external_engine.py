"""What the clients for user-installed speech engines share (ADR-008).

The engines (VOICEVOX, SHAREVOX, AivisSpeech, COEIROINK v2) run on the user's PC and answer a
whole WAV per request, so the text is split into sentences and each sentence is synthesized and
played in turn. Only loopback URLs are used (`local_url`), engines are never started or installed
by the app, and errors carry safe codes only: no text, audio or response body.
"""
from dataclasses import dataclass
import http.client
import io
import json
import queue
import re
import socket
from threading import Thread
from urllib.parse import urlsplit
import wave

from models.http_stream import InterruptibleSocket
from models.voice_events import AudioFrame
from .settings import local_url
from .speechcpp_tts import CancelToken, SpeechError

# On this project's test PC (Windows 11, i7-1255U, CPU builds) a 32-character sentence took about
# 4 s in VOICEVOX 0.26.1 and 2.4 s in COEIROINK 2.13.0. Microphone speech must start within 5 s, so
# long sentences are also split at commas.
MAX_PIECE = 40
MAX_TEXT = 4000
FRAME_SECONDS = 0.2
MAX_AUDIO_SECONDS = 60
PREFETCH = 1  # Sentences synthesized ahead of the one playing.
SENTENCE_END = re.compile(r'(?<=[。！？!?．])|\n+')
COMMA = re.compile(r'(?<=[、，,])')


@dataclass(frozen=True)
class EngineVoice:
    """A saved voice: the engine's id plus the names it had, to find it again if the id changes."""
    id: str
    speaker: str = ''
    style: str = ''


def split_text(text):
    """Sentences, and sentences longer than MAX_PIECE characters cut at commas where possible."""
    pieces = []
    for sentence in SENTENCE_END.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= MAX_PIECE:
            pieces.append(sentence)
            continue
        current = ''
        for part in COMMA.split(sentence):
            if current and len(current) + len(part) > MAX_PIECE:
                pieces.append(current.strip())
                current = ''
            current += part
        if current.strip():
            pieces.append(current.strip())
    return [piece for piece in pieces if piece]


def wav_frames(data, budget):
    """AudioFrames of about FRAME_SECONDS from a 16-bit PCM WAV, in memory.

    `budget` is a one-item list with the samples still allowed for the message (None until the
    first WAV gives its rate); it shrinks.
    """
    try:
        with wave.open(io.BytesIO(data)) as reader:
            rate, channels, width = reader.getframerate(), reader.getnchannels(), reader.getsampwidth()
            frames = reader.readframes(reader.getnframes())
    except (wave.Error, EOFError):
        raise SpeechError('invalid_wav') from None
    if width != 2 or channels not in (1, 2):
        raise SpeechError('unsupported_wav')
    try:
        AudioFrame(b'', rate, channels)
    except ValueError:
        raise SpeechError('invalid_sample_rate') from None
    frame_bytes = 2 * channels
    samples = len(frames) // frame_bytes
    if not samples:
        raise SpeechError('empty_pcm')
    if budget[0] is None:
        budget[0] = rate * MAX_AUDIO_SECONDS
    budget[0] -= samples
    if budget[0] < 0:
        raise SpeechError('audio_duration_limit')
    step = max(1, int(rate * FRAME_SECONDS)) * frame_bytes
    for start in range(0, samples * frame_bytes, step):
        yield AudioFrame(frames[start:start + step], rate, channels)


def find_voice(voices, voice):
    """The engine's id for `voice`: by id when the names still match, otherwise by names."""
    if not isinstance(voice, EngineVoice) or not voice.id:
        raise SpeechError('tts_engine_voice_unset')
    by_id = next((row for row in voices if row['id'] == voice.id), None)
    if by_id is not None and (not voice.speaker or (by_id['speaker'], by_id['style']) == (voice.speaker, voice.style)):
        return by_id['id']
    by_name = next((row for row in voices if (row['speaker'], row['style']) == (voice.speaker, voice.style)), None)
    if by_name is None or not voice.speaker:
        raise SpeechError('tts_engine_voice_missing')
    return by_name['id']


class EngineClient:
    """HTTP to one engine. One request at a time; cancellation shuts the socket."""
    not_ready = 'tts_engine_not_ready'

    def __init__(self, base_url, timeout=2.0, synthesis_timeout=30.0):
        self.base_url = local_url(base_url)
        self.timeout = timeout
        self.synthesis_timeout = synthesis_timeout

    def request(self, method, path, token, *, body=None, limit, error_code, timeout=None, expect=None):
        url = urlsplit(self.base_url)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=self.timeout)
        try:
            token.check()
            conn.connect()
            sock = conn.sock = InterruptibleSocket(conn.sock)

            def interrupt():
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            token.register(interrupt)
            token.check()
            # bytes are JSON already (an engine's own AudioQuery) and go back unchanged.
            payload = body if body is None or isinstance(body, bytes) else json.dumps(body).encode()
            headers = {'Content-Type': 'application/json'} if body is not None else {}
            conn.request(method, path, payload, headers)
            sock.settimeout(timeout or self.timeout)
            response = conn.getresponse()
            data = response.read(limit + 1)
            token.check()
            if response.status != 200:
                raise SpeechError(f'http_{response.status}')
            if len(data) > limit:
                raise SpeechError('response_too_large')
            kind = response.getheader('Content-Type', '').split(';')[0].strip().lower()
            if expect and kind != expect:
                raise SpeechError(error_code)
            return data
        except TimeoutError:
            token.check()
            raise SpeechError(error_code) from None
        except (OSError, http.client.HTTPException):
            token.check()
            raise SpeechError(error_code) from None
        finally:
            conn.close()

    def get_json(self, path, token, *, limit, error_code=None):
        data = self.request('GET', path, token, limit=limit, error_code=error_code or self.not_ready)
        try:
            return json.loads(data)
        except ValueError:
            raise SpeechError(error_code or self.not_ready) from None

    # Implemented by each engine.
    def list_voices(self, cancel_token=None):
        raise NotImplementedError

    def synthesize_piece(self, text, voice_id, token):
        raise NotImplementedError

    def synthesize_stream(self, text, voice, language, cancel_token, **_options):
        """Sentence by sentence; seed and instructions are speech.cpp options and do not apply."""
        if language != 'ja':
            raise SpeechError('tts_engine_language')
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise SpeechError('invalid_text')
        voice_id = find_voice(self.list_voices(cancel_token), voice)
        pieces = split_text(text)
        if not pieces:
            raise SpeechError('invalid_text')
        # Playback writes at the device's pace, so the next sentence is synthesized while this one
        # plays; otherwise each sentence would wait for the last to finish (a 1-2 s gap on CPU).
        # `inner` stops the prefetch when the message is cancelled or playback ends early.
        inner = CancelToken()
        cancel_token.register(inner.cancel)
        results = queue.Queue(maxsize=PREFETCH)

        def produce():
            try:
                for piece in pieces:
                    _put(results, ('wav', self.synthesize_piece(piece, voice_id, inner)), inner)
                _put(results, ('end', None), inner)
            except SpeechError as error:
                _put(results, ('error', str(error)), inner)
            except Exception:
                _put(results, ('error', 'tts_engine_synthesis_failed'), inner)

        worker = Thread(target=produce, name='vrct-vox-engine-prefetch', daemon=True)
        worker.start()
        budget = [None]
        try:
            while True:
                kind, value = _get(results, cancel_token)
                if kind == 'end':
                    return
                if kind == 'error':
                    cancel_token.check()
                    raise SpeechError(value)
                for frame in wav_frames(value, budget):
                    cancel_token.check()
                    yield frame
        finally:
            inner.cancel()


def _put(results, item, token):
    while not token.is_set():
        try:
            results.put(item, timeout=0.05)
            return
        except queue.Full:
            continue


def _get(results, token):
    while True:
        token.check()
        try:
            return results.get(timeout=0.05)
        except queue.Empty:
            continue


def probe(client, cancel_token=None):
    """True when the engine answers; never synthesizes anything."""
    try:
        client.check_health(cancel_token or CancelToken())
        return True
    except SpeechError:
        return False
