"""Optional bounded warm requests to an owned Irodori GPU server.

Generated frames are discarded here: no router, user text, microphone or queue.
This trades idle power for latency; it is never enabled by default.
"""
from threading import Event, Lock, Thread, Timer
from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS


class LowLatencyStandby:
    def __init__(self, url, *, synthesize=None, interval=.1):
        provider = SpeechCppTTS(url, timeout=1, first_audio_timeout=2)
        self._synthesize = synthesize or (lambda token: provider.synthesize_stream(
            'あ。', 'none', 'ja', token, seed=0))
        self._interval = interval
        self._stop, self._lock = Event(), Lock()
        self._token = self._thread = None
        self._state = dict(state='warming', completed=0, error_code=None)

    def health(self):
        with self._lock:
            return dict(self._state)

    def start(self):
        if self._thread is not None or self._stop.is_set():
            raise RuntimeError('low_latency_single_use')
        self._thread = Thread(target=self._run, name='vrct-tts-standby', daemon=True)
        self._thread.start()

    def close(self, timeout=1):
        self._stop.set()
        with self._lock:
            token = self._token
        if token is not None:
            token.cancel()
        if self._thread is not None:
            self._thread.join(timeout)
        return self._thread is None or not self._thread.is_alive()

    def _run(self):
        try:
            while not self._stop.is_set():
                token = CancelToken()
                with self._lock:
                    self._token = token
                    if self._stop.is_set():
                        break
                # Bound the entire discard operation, including a stalled body.
                timer = Timer(2, lambda: token.cancel('standby_timeout'))
                timer.daemon = True
                timer.start()
                stream = None
                try:
                    stream = self._synthesize(token)
                    for _frame in stream:
                        token.check()
                    token.check()
                finally:
                    if stream is not None and hasattr(stream, 'close'):
                        stream.close()
                    timer.cancel()
                    timer.join()
                with self._lock:
                    self._token = None
                    self._state.update(state='ready', completed=self._state['completed'] + 1)
                if self._stop.wait(self._interval):
                    break
        except Exception:
            with self._lock:
                self._state.update(state='failed', error_code='speech_server_low_latency_failed')
        finally:
            with self._lock:
                self._token = None
                if self._stop.is_set():
                    self._state.update(state='stopped', error_code=None)
