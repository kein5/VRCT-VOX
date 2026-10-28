"""One source owns capture, transport and a bounded, nonblocking subtitle mailbox."""

import asyncio
from dataclasses import replace
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, current_thread
from time import monotonic_ns

from models.tts.speechcpp_tts import CancelToken
from .capture_pipewire import PipeWireCapture, _validate
from .realtime_audio import RealtimeIngress
from .realtime_settings import SessionOptions
from .speechcpp_asr import SpeechCppASR
from .speechcpp_realtime import SpeechCppRealtime


class SessionError(RuntimeError):
    """Fixed diagnostic code only."""


class RealtimeSession:
    def __init__(
        self,
        source,
        options,
        endpoint,
        *,
        capture_factory=PipeWireCapture,
        client_factory=SpeechCppRealtime,
    ):
        _validate(endpoint, source)
        if not isinstance(options, SessionOptions):
            raise ValueError("realtime_options_invalid")
        self.source, self.options, self.endpoint = source, options, endpoint
        self._capture_factory, self._client_factory = capture_factory, client_factory
        self._lock = Lock()
        self._stop = Event()
        self._cancel = CancelToken()
        self._updates = Queue(maxsize=32)
        self._thread = self._loop = self._stop_async = None
        self._client = self._capture = self._ingress = None
        self._state, self._error, self._namespace = "idle", None, None

    def health(self):
        with self._lock:
            return dict(
                source=self.source,
                state=self._state,
                namespace=self._namespace,
                error_code=self._error,
            )

    def is_current(self, namespace):
        with self._lock:
            return (
                not self._stop.is_set()
                and self._state == "ready"
                and namespace == self._namespace
            )

    def start(self):
        with self._lock:
            if self._thread is not None or self._stop.is_set():
                raise SessionError("realtime_session_single_use")
            self._state = "starting"
            self._thread = Thread(
                target=self._thread_main, name="realtime-" + self.source, daemon=True
            )
            self._thread.start()

    def _discard_updates(self):
        while True:
            try:
                self._updates.get_nowait()
            except Empty:
                return

    def request_stop(self):
        """Invalidate output/startup now; close() is the resource completion boundary."""
        with self._lock:
            self._stop.set()
            self._discard_updates()
            if self._state not in ("failed", "closed"):
                self._state = "stopping" if self._thread is not None else "closed"
            if self._ingress:
                self._ingress.close()
            if self._capture:
                self._capture.request_stop()
            loop, signal = self._loop, self._stop_async
        self._cancel.cancel()
        if loop and signal:
            try:
                loop.call_soon_threadsafe(signal.set)
            except RuntimeError:
                pass  # loop teardown already invalidated this single-use owner

    def close(self, timeout=3):
        self.request_stop()
        with self._lock:
            thread = self._thread
        if thread:
            if thread is current_thread():
                return False
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def pop_update(self, timeout=0.05):
        if self._stop.is_set():
            return None
        try:
            update = self._updates.get(timeout=timeout)
        except Empty:
            return None
        return update if self.is_current(update.namespace) else None

    def _fail(self, code):
        with self._lock:
            self._error, self._state = code, "failed"
        self.request_stop()

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except Exception:
            self._fail("realtime_session_failed")
        finally:
            with self._lock:
                self._stop.set()
                self._discard_updates()
                if self._state != "failed":
                    self._state = "closed"
                self._loop = self._stop_async = None

    def _preflight(self):
        models = SpeechCppASR(self.options.base_url, timeout=5).recognizers(
            self._cancel
        )
        selected = next(
            (model for model in models if model.id == self.options.model), None
        )
        if selected is None:
            raise SessionError("realtime_model_unavailable")
        if self.options.language not in selected.languages:
            raise SessionError("realtime_language_unsupported")

    async def _consume(self):
        await asyncio.to_thread(self._preflight)
        if self._stop.is_set():
            return
        client = self._client_factory(
            self.options.base_url,
            self.options.model,
            self.options.language,
            self.source,
        )
        with self._lock:
            self._client, self._namespace = client, client.namespace
        await client.start()
        if self._stop.is_set():
            return
        ingress = RealtimeIngress(48000, 1)

        def capture_error(code):
            self._fail("realtime_capture_failed")

        with self._lock:
            if self._stop.is_set():
                return
            self._ingress = ingress
            self._capture = self._capture_factory(
                self.endpoint,
                self.source,
                lambda frame: ingress.push(frame.audio, frame.captured_ns),
                capture_error,
            )
            capture = self._capture
        pump = asyncio.create_task(ingress.pump(client))
        try:
            await asyncio.to_thread(capture.start)
            with self._lock:
                if self._stop.is_set():
                    return
                self._state = "ready"
            while not self._stop.is_set():
                update = await client.next_update()
                if not update.received_ns:
                    update = replace(update, received_ns=monotonic_ns())
                with self._lock:
                    if self._stop.is_set():
                        return
                    try:
                        self._updates.put_nowait(update)
                    except Full:
                        raise SessionError("realtime_updates_overflow") from None
        finally:
            ingress.close()
            await pump

    async def _serve(self):
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._stop_async = asyncio.Event()
            if self._stop.is_set():
                self._stop_async.set()
        worker = asyncio.create_task(self._consume())
        stopper = asyncio.create_task(self._stop_async.wait())
        try:
            done, _ = await asyncio.wait(
                (worker, stopper), return_when=asyncio.FIRST_COMPLETED
            )
            if worker in done:
                await worker
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if not self._stop.is_set():
                self._fail(
                    str(exc)
                    if isinstance(exc, SessionError)
                    else "realtime_session_failed"
                )
        finally:
            self.request_stop()
            if self._client:
                await self._client.stop()
            if self._capture:
                try:
                    await asyncio.to_thread(self._capture.stop)
                except Exception:
                    self._fail("realtime_capture_stop_failed")
            worker.cancel()
            stopper.cancel()
            await asyncio.gather(worker, stopper, return_exceptions=True)
