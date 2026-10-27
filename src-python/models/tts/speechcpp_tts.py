"""speech.cpp's documented PCM API; no SDK defaults or model downloads."""
import http.client
import json
import socket
from threading import Event, Lock
from urllib.parse import urlsplit

from models.voice_events import AudioFrame
from .settings import local_url


class SpeechError(Exception):
    """Safe code only: never expose server bodies, text or voice data in logs."""


class CancelToken:
    def __init__(self):
        self._event = Event()
        self._lock = Lock()
        self._closers = []
        self.reason = "cancelled"

    def is_set(self):
        return self._event.is_set()

    def wait(self, timeout):
        return self._event.wait(timeout)

    def check(self):
        if self.is_set():
            raise SpeechError(self.reason)

    def register(self, closer):
        with self._lock:
            if not self.is_set():
                self._closers.append(closer)
                return
        closer()

    def cancel(self, reason="cancelled"):
        with self._lock:
            if self.is_set():
                return
            self.reason = reason
            self._event.set()
            closers, self._closers = self._closers, []
        for closer in closers:
            try:
                closer()
            except OSError:
                pass


class SpeechCppTTS:
    def __init__(self, base_url, timeout=2.0):
        self.base_url = local_url(base_url)
        self.timeout = timeout

    def synthesize_stream(self, text, voice, language, cancel_token):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise SpeechError("invalid_text")
        url = urlsplit(self.base_url)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=self.timeout)
        response = None
        try:
            cancel_token.check()
            conn.connect()
            sock = conn.sock

            def interrupt():
                # shutdown wakes read1/getresponse without closing a file object
                # concurrently with its reader. Worker owns final close.
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            cancel_token.register(interrupt)
            cancel_token.check()
            body = json.dumps({"input": text, "voice": voice,
                               "language": language, "response_format": "pcm"}).encode()
            conn.request("POST", "/v1/audio/speech", body, {"Content-Type": "application/json"})
            response = conn.getresponse()
            if response.status != 200:
                raise SpeechError(f"http_{response.status}")
            if response.getheader("Content-Type", "").split(";")[0].strip().lower() != "audio/pcm":
                raise SpeechError("expected_pcm")
            try:
                rate = int(response.getheader("X-Sample-Rate", ""))
                AudioFrame(b"", rate)
            except ValueError:
                raise SpeechError("invalid_sample_rate") from None
            pending = b""
            samples = 0
            while True:
                cancel_token.check()
                chunk = response.read1(4096)
                cancel_token.check()
                if not chunk:
                    break
                pending += chunk
                complete = len(pending) // 2 * 2
                if complete:
                    samples += complete // 2
                    if samples > rate * 60:
                        raise SpeechError("audio_duration_limit")
                    yield AudioFrame(pending[:complete], rate)
                    pending = pending[complete:]
            if pending:
                raise SpeechError("truncated_pcm")
            if not samples:
                raise SpeechError("empty_pcm")
            if response.length not in (None, 0):
                raise SpeechError("truncated_http")
        except (OSError, http.client.HTTPException) as exc:
            cancel_token.check()
            raise SpeechError("transport_error") from exc
        finally:
            if response is not None:
                response.close()
            conn.close()
