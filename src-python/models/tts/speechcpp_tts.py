"""speech.cpp's documented PCM API; no SDK defaults or model downloads."""
import http.client
import json
import socket
import sys
from threading import Event, Lock, Thread, Timer
from time import monotonic
from urllib.parse import urlsplit

from models.voice_events import AudioFrame
from models.http_stream import InterruptibleSocket
from .settings import local_url
from .model_options import parse_options, SAFE_SEED_MAX
from .listener_table import windows_listener_table


class SpeechError(Exception):
    """Safe code only: never expose server bodies, text or voice data in logs."""


class CancelToken:
    def __init__(self, *, start_deadline=None):
        self._event = Event()
        self._lock = Lock()
        self._closers = []
        self.reason = "cancelled"
        self._start_deadline = start_deadline
        self._started = False

    def is_set(self):
        return self._event.is_set()

    def wait(self, timeout):
        return self._event.wait(timeout)

    def check(self):
        self.expire_start()
        if self.is_set():
            raise SpeechError(self.reason)

    def _expire_start_locked(self):
        if (not self._started and self._start_deadline is not None
                and monotonic() >= self._start_deadline):
            return self._cancel_locked("speech_expired")
        return []

    def expire_start(self):
        with self._lock:
            closers = self._expire_start_locked()
        self._close(closers)

    def begin_playback(self):
        # The expiry callback and first non-silent write compete under one lock.
        with self._lock:
            closers = self._expire_start_locked()
            if not self.is_set():
                self._started = True
        self._close(closers)
        self.check()

    def commit_audio_write(self, pcm, write):
        """Serialize expiry with a NONBLOCKING write, never a readiness wait.

        Only successfully written nonzero bytes end the startup deadline.
        A partial all-zero prefix or EAGAIN leaves expiry active.
        """
        count = None
        with self._lock:
            closers = self._expire_start_locked()
            if not self.is_set():
                count = write()
                if type(count) is not int or not 0 < count <= len(pcm):
                    raise SpeechError('output_write_invalid')
                if any(pcm[:count]):
                    self._started = True
        self._close(closers)
        self.check()
        return count

    def register(self, closer):
        with self._lock:
            if not self.is_set():
                self._closers.append(closer)
                return
        closer()

    def cancel(self, reason="cancelled"):
        with self._lock:
            closers = self._cancel_locked(reason)
        self._close(closers)

    def _cancel_locked(self, reason):
        if self.is_set():
            return []
        self.reason = reason
        self._event.set()
        closers, self._closers = self._closers, []
        return closers

    @staticmethod
    def _close(closers):
        for closer in closers:
            try:
                closer()
            except OSError:
                pass


def _windows_listener_missing(address, stopped=None):
    """Winsock may retry refused connects beyond the short probe timeout.

    A successful Windows TCP table query can establish listener absence without
    consuming response PCM. Failure to read the table remains inconclusive.
    No remote connection addresses or process details are retained or published.
    """
    host, port = address
    addresses = {'::1', '::'} if host == '::1' else {'127.0.0.1', '0.0.0.0', '::'}
    if host == 'localhost':
        addresses.add('::1')
    rows = windows_listener_table.read(stopped if stopped is not None else Event())
    if rows is None:
        return False
    return not any(ip in addresses and local_port == port for ip, local_port in rows)


def _watch_listener(address, token, stopped):
    """Detect a refused localhost listener independently of playback-paced reads.

    This is not a health check: a timeout or other inconclusive connect failure
    does not prove the server died. Existing HTTP/request deadlines still apply.
    No PCM is read or queued here, and only this request's token is cancelled.
    """
    while not stopped.wait(.02) and not token.is_set():
        if sys.platform == 'win32' and _windows_listener_missing(address, stopped):
            if not stopped.is_set():
                token.cancel("server_unavailable")
            return
        try:
            with socket.create_connection(address, timeout=.1):
                pass
        except ConnectionRefusedError:
            if not stopped.is_set():
                token.cancel("server_unavailable")
            return
        except OSError:
            # A busy listener, local resource pressure, etc. is inconclusive.
            pass


class SpeechCppTTS:
    def __init__(self, base_url, timeout=2.0, first_audio_timeout=10.0):
        self.base_url = local_url(base_url)
        self.timeout = timeout
        self.first_audio_timeout = first_audio_timeout

    def check_health(self):
        """Bounded, local-only readiness probe; never loads or synthesizes a model."""
        if self._get_json('/health', 4096, CancelToken(), 'speech_server_not_ready') != {'status': 'ok'}:
            raise SpeechError('speech_server_not_ready')

    def _get_json(self, path, limit, token, error_code):
        url = urlsplit(self.base_url)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=self.timeout)
        expired = Event()
        sock = None
        def interrupt():
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        def expire():
            expired.set()
            interrupt()
        timer = Timer(self.timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            token.check()
            conn.connect()
            sock = conn.sock = InterruptibleSocket(conn.sock)
            token.register(interrupt)
            token.check()
            if expired.is_set():
                raise SpeechError(error_code)
            conn.request('GET', path)
            response = conn.getresponse()
            body = response.read(limit + 1)
            token.check()
            if expired.is_set() or response.status != 200 or len(body) > limit:
                raise SpeechError(error_code)
            return json.loads(body)
        except (OSError, ValueError, http.client.HTTPException):
            token.check()
            raise SpeechError(error_code) from None
        finally:
            timer.cancel()
            conn.close()

    def get_model_options(self, cancel_token=None):
        document = self._get_json('/v1/models', 65536, cancel_token or CancelToken(), 'tts_model_options_unavailable')
        try:
            return parse_options(document)
        except ValueError:
            raise SpeechError('tts_model_options_unavailable') from None

    def synthesize_stream(self, text, voice, language, cancel_token, *, seed=None, instructions=''):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise SpeechError("invalid_text")
        if seed is not None and (type(seed) is not int or not 0 <= seed <= SAFE_SEED_MAX):
            raise SpeechError('invalid_seed')
        if (not isinstance(instructions, str) or len(instructions) > 4000
                or any((ord(c) < 32 and c not in '\r\n\t') or ord(c) == 127 for c in instructions)):
            raise SpeechError('invalid_instructions')
        options = {}
        if seed is not None or instructions.strip():
            capability = self.get_model_options(cancel_token)
            if seed is not None:
                limits = capability['seed']
                if limits is None:
                    raise SpeechError('tts_seed_unsupported')
                if not limits['minimum'] <= seed <= limits['maximum']:
                    raise SpeechError('tts_seed_out_of_range')
                options['seed'] = seed
            if instructions.strip():
                if not capability['instructions']:
                    raise SpeechError('tts_instructions_unsupported')
                options['instructions'] = instructions
        url = urlsplit(self.base_url)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=self.timeout)
        response = None
        waiting_for_audio = False
        watch_stopped, watcher = Event(), None
        try:
            cancel_token.check()
            conn.connect()
            sock = conn.sock = InterruptibleSocket(conn.sock)

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
                               "language": language, "response_format": "pcm", **options}).encode()
            conn.request("POST", "/v1/audio/speech", body, {"Content-Type": "application/json"})
            # Initial model work can include cold Vulkan kernels. Keep connection
            # and subsequent chunk stalls short, but allow bounded first audio.
            waiting_for_audio = True
            first_audio_deadline = monotonic() + self.first_audio_timeout
            sock.settimeout(self.first_audio_timeout)
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
                if waiting_for_audio:
                    remaining = first_audio_deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    sock.settimeout(remaining)
                chunk = response.read1(4096)
                cancel_token.check()
                if not chunk:
                    break
                pending += chunk
                complete = len(pending) // 2 * 2
                if complete:
                    if waiting_for_audio:
                        waiting_for_audio = False
                        sock.settimeout(self.timeout)
                        # The generator may next be suspended inside a slow
                        # output.write; do not wait for its next HTTP read to
                        # notice that the external server is no longer there.
                        watcher = Thread(target=_watch_listener,
                                         args=((url.hostname, url.port or 80), cancel_token, watch_stopped),
                                         name="vrct-vox-listener", daemon=True)
                        watcher.start()
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
        except TimeoutError as exc:
            cancel_token.check()
            raise SpeechError("first_audio_timeout" if waiting_for_audio else "transport_error") from exc
        except (OSError, http.client.HTTPException) as exc:
            cancel_token.check()
            raise SpeechError("transport_error") from exc
        finally:
            watch_stopped.set()
            if watcher is not None:
                watcher.join()
            if response is not None:
                response.close()
            conn.close()
