"""One bounded worker; chat delivery never waits for HTTP or audio devices."""
from collections import OrderedDict, deque
from threading import Condition, Event, Thread, Timer
from time import monotonic, monotonic_ns

from models.audio_routing.audio_router import AudioRouter
from models.audio_routing.monitor_output import MonitorTee
from .settings import VoiceSettings
from .speechcpp_tts import CancelToken, SpeechCppTTS, SpeechError
from .voice_trace import write_voice_trace, install_gc_diagnostics


class StartExpiry:
    """Expire a token's start deadline once it has really passed.

    A one-shot threading.Timer is not enough: on Windows a timed wait can
    return a little before monotonic() reaches the deadline (~15.6 ms timer
    tick). expire_start() then sees an unexpired deadline and nothing ever
    retries, so a stalled server held the job until the request timeout.
    """

    def __init__(self, token, deadline):
        self._token, self._deadline = token, deadline
        self._stopped = Event()
        self._thread = Thread(target=self._run, name="vrct-vox-start-expiry", daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _run(self):
        while not self._stopped.is_set():
            remaining = self._deadline - monotonic()
            if remaining <= 0:
                self._token.expire_start()
                return
            self._stopped.wait(remaining)

    def cancel(self):
        self._stopped.set()


class VoiceEventBus:
    """Serialize final chat and opted-in microphone translations."""
    def __init__(self, settings=None, *, provider_factory=SpeechCppTTS, router=None,
                 capacity=4, max_age=5.0, request_timeout=30.0, resolve_server=None, enabled=True,
                 monitor_factory=MonitorTee, on_monitor_error=None):
        install_gc_diagnostics()
        self.settings = settings or VoiceSettings()
        self.provider_factory = provider_factory
        self.resolve_server = resolve_server
        self.router = router or AudioRouter()
        self.monitor_factory = monitor_factory
        self.on_monitor_error = on_monitor_error
        self.capacity = capacity
        self.max_age = max_age
        self.request_timeout = request_timeout
        self._condition = Condition()
        self._queue = deque()
        self._seen = OrderedDict()
        self._thread = None
        self._active = None
        self._active_source = None
        self._closed = False
        self._muted = False
        self._tts_enabled = bool(enabled)
        self._observation_id = 0
        self._epoch = 0
        self._source_epochs = {}
        self._stats = {"accepted": 0, "completed": 0, "dropped": 0, "duplicates": 0,
                       "cancelled": 0, "errors": 0, "last_error": None,
                       "last_first_write_ms": None, "sample_rate": None, "monitor_error": None}

    def configure(self, settings):
        with self._condition:
            self.settings = settings
            self._cancel_locked()
            self._stats["last_error"] = None
            self._stats["monitor_error"] = None

    def _cancel_locked(self):
        self._epoch += 1
        self._stats["dropped"] += len(self._queue)
        self._queue.clear()
        if self._active:
            self._active.cancel()
        self._condition.notify_all()

    def cancel(self):
        with self._condition:
            self._cancel_locked()

    def set_enabled(self, enabled, expected_generation=None):
        if type(enabled) is not bool:
            raise ValueError('invalid_tts_toggle')
        with self._condition:
            if self._closed or (expected_generation is not None and
                                (type(expected_generation) is not int or expected_generation != self._epoch)):
                return False
            if enabled and self._muted:
                return False
            if not enabled or self._tts_enabled != enabled:
                self._tts_enabled = enabled
                # The same epoch invalidates pending finals, saves and late enables.
                self._cancel_locked()
            return True

    def set_muted(self, muted):
        with self._condition:
            if self._muted != bool(muted):
                self._muted = bool(muted)
                # Both edges invalidate chat accepted before the transition.
                self._cancel_locked()

    def close(self, timeout=3.0):
        with self._condition:
            self._closed = True
            self._cancel_locked()
            thread = self._thread
        if thread:
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def generation(self):
        with self._condition:
            return self._epoch

    def source_generation(self, source):
        with self._condition:
            return self._source_epochs.get(source, 0)

    def cancel_source(self, source):
        with self._condition:
            self._source_epochs[source] = self._source_epochs.get(source, 0) + 1
            retained = deque(item for item in self._queue if item[0].source != source)
            self._stats["dropped"] += len(self._queue) - len(retained)
            self._queue = retained
            if self._active_source == source and self._active:
                self._active.cancel()
            self._condition.notify_all()

    def publish(self, event, *, expected_generation=None, expected_source_generation=None):
        with self._condition:
            if expected_generation is not None and expected_generation != self._epoch:
                return False
            if (expected_source_generation is not None and
                    expected_source_generation != self._source_epochs.get(event.source, 0)):
                return False
            if self._closed or self._muted or not self._tts_enabled or not event.is_final:
                return False
            if event.source == "chat":
                if self.settings.mode == "off":
                    return False
            elif event.source == "mic":
                if self.settings.mic_mode != "translated" or not (event.translated_text or "").strip():
                    return False
                if event.timestamp_ns <= 0 or event.timestamp_ns > monotonic_ns():
                    self._stats["dropped"] += 1
                    return False
            else:
                return False
            if not event.event_id or not event.original_text.strip():
                return False
            now = monotonic()
            while self._seen and next(iter(self._seen.values())) < now - 120:
                self._seen.popitem(last=False)
            key = (event.source, event.utterance_id or event.event_id)
            if key in self._seen:
                self._stats["duplicates"] += 1
                return False
            if len(self._queue) >= self.capacity:
                oldest_mic = next((i for i, item in enumerate(self._queue) if item[0].source == "mic"), None)
                if oldest_mic is None and event.source == "mic":
                    self._stats["dropped"] += 1
                    return False
                del self._queue[oldest_mic if oldest_mic is not None else 0]
                self._stats["dropped"] += 1
            self._seen[key] = now
            while len(self._seen) > 512:
                self._seen.popitem(last=False)
            self._queue.append((event, self.settings, self._epoch))
            self._stats["accepted"] += 1
            if self._thread is None:
                self._thread = Thread(target=self._work, name="vrct-vox", daemon=True)
                self._thread.start()
            self._condition.notify()
            return True

    def status(self):
        with self._condition:
            self._observation_id = max(monotonic_ns(), self._observation_id + 1)
            return {**self._stats, "queued": len(self._queue), "active": self._active is not None,
                    "mode": self.settings.mode, "closed": self._closed, "muted": self._muted,
                    "tts_enabled": self._tts_enabled, "tts_generation": self._epoch,
                    "tts_stopping": not self._tts_enabled and self._active is not None,
                    "observation_id": str(self._observation_id)}

    def _open_monitor(self, settings, epoch):
        """Optional and isolated: a monitor problem is a notice, never a speech error."""
        choice = settings.monitor_choice
        if choice is None or self.monitor_factory is None:
            return None

        def failed(code):
            with self._condition:
                if epoch == self._epoch:
                    self._stats["monitor_error"] = code
            if self.on_monitor_error is not None:
                self.on_monitor_error(code)

        def ready():
            with self._condition:
                if epoch == self._epoch:
                    self._stats["monitor_error"] = None

        device, volume = choice
        try:
            return self.monitor_factory(device, volume, exclude=(settings.playback_device,),
                                        on_error=failed, on_ready=ready)
        except Exception:
            failed("monitor_output_error")
            return None

    def _work(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._queue)
                if self._closed:
                    return
                next_chat = next((i for i, item in enumerate(self._queue) if item[0].source == "chat"), 0)
                event, settings, epoch = self._queue[next_chat]
                del self._queue[next_chat]
                if monotonic_ns() - event.timestamp_ns > self.max_age * 1e9:
                    self._stats["dropped"] += 1
                    continue
                deadline = event.timestamp_ns / 1e9 + self.max_age if event.source == "mic" else None
                token = self._active = CancelToken(start_deadline=deadline)
                self._active_source = event.source
            start_timer = None
            if deadline is not None:
                start_timer = StartExpiry(token, deadline).start()
            timer = Timer(self.request_timeout, lambda: token.cancel("request_timeout"))
            timer.daemon = True
            timer.start()
            frames = None
            monitor = None
            first_write = None
            outcome = "error"
            try:
                url, voice, language, text = settings.request_for(event, resolve_server=self.resolve_server)
                frames = self.provider_factory(url).synthesize_stream(text, voice, language, token,
                                                                    **settings.options_for(language))

                def first_audio(timestamp, rate):
                    nonlocal first_write
                    first_write = (timestamp, rate)
                    with self._condition:
                        self._stats["last_first_write_ms"] = round((timestamp - event.timestamp_ns) / 1e6, 3)
                        self._stats["sample_rate"] = rate

                monitor = self._open_monitor(settings, epoch)
                if monitor is None:
                    self.router.play(frames, settings.playback_device, token, first_audio)
                else:
                    self.router.play(frames, settings.playback_device, token, first_audio, monitor=monitor)
                token.check()
                outcome = "completed"
                with self._condition:
                    self._stats["completed"] += 1
                    if epoch == self._epoch:
                        self._stats["last_error"] = None
            except Exception as exc:
                with self._condition:
                    if token.is_set() and token.reason == "cancelled":
                        outcome = "cancelled"
                        self._stats["cancelled"] += 1
                    else:
                        self._stats["errors"] += 1
                        if epoch == self._epoch:
                            # ValueError and OS/driver exceptions can include input
                            # content or device paths. Never put those into status.
                            self._stats["last_error"] = (token.reason if token.is_set() else
                                                         str(exc) if isinstance(exc, SpeechError) else
                                                         "language_or_text_unavailable" if isinstance(exc, ValueError) else
                                                         "audio_output_error")
            finally:
                if monitor is not None:
                    monitor.close(drain=outcome == "completed")  # Idempotent; never waits.
                timer.cancel()
                if start_timer is not None:
                    start_timer.cancel()
                if frames is not None:
                    try:
                        frames.close()
                    except Exception:
                        pass
                write_voice_trace(event.event_id, event.timestamp_ns, first_write, outcome)
                with self._condition:
                    self._active = None
                    self._active_source = None
                    self._condition.notify_all()
