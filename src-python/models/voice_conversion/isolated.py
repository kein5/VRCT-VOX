"""Control-only owner of a fixed, separately executed VC transport process."""
import os
from pathlib import Path
import subprocess
from runtime_paths import resource_root, external_process_env
import sys
from threading import Event, Lock, Thread, current_thread, get_native_id
import time

from models.audio_routing.monitor_output import parse_monitor
from models.audio_routing.source_bridge import _source_id
from models.owned_child import PipeWriter, launch_owned
from models.transcription.capture_pipewire import _validate
from .router_protocol import BASE_STATE, Reader, encode, speech_frame, validate_health
from .settings import start_options

ROOT = resource_root()
HELPER = ROOT / 'build/vrct-vc-worker'
# A Windows router pays for its Python imports before its first health frame.
OWNED_ROUTER_START = 30
# Speech through the conversion (ADR-007): one 80 ms block per frame, sent at most
# this far ahead of real time, and waited out by about two conversion blocks.
SPEECH_FRAME = 7680
SPEECH_LEAD_NS = 400_000_000
SPEECH_TAIL_NS = 250_000_000


def _launch_owned():
    """The Windows router: no helper or graph feed, a job holds its lifetime."""
    env = external_process_env()
    frozen = bool(getattr(sys, 'frozen', False))
    if not frozen:
        env['PYTHONPATH'] = str(ROOT / 'src-python') + os.pathsep + str(ROOT)
    command = ['--voice-router-worker'] if frozen else ['-u', '-m', 'models.voice_conversion.router_worker']
    return launch_owned([sys.executable, *command], env=env, cwd=ROOT, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, realtime=True)


def _launch(source, output=None):
    if output is not None:
        return _launch_owned()
    from models.audio_routing.pipewire_graph_pipe import GraphFeed, _ENV
    from models.audio_routing.pipewire_gate import VC_SINK
    feed = GraphFeed((source.name, VC_SINK))
    try:
        return _launch_with_graph(feed, _ENV)
    except BaseException:
        feed.close()
        raise


def _launch_with_graph(feed, key):
    owner = os.pidfd_open(get_native_id(), os.O_EXCL)
    env = external_process_env()
    env[key] = str(feed.read_fd)
    frozen = bool(getattr(sys, 'frozen', False))
    if not frozen:
        # Fixed application code, independent of the shell's PYTHONPATH.
        env['PYTHONPATH'] = str(ROOT / 'src-python') + os.pathsep + str(ROOT)
    try:
        child = subprocess.Popen([str(HELPER), str(os.getpid()), str(owner), sys.executable,
            'router-frozen' if frozen else 'router'], cwd=ROOT, env=env, pass_fds=(owner, feed.read_fd),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        child.graph_feed = feed
        feed.close_reader()
        return child
    finally:
        os.close(owner)


class IsolatedVCProcess:
    def __init__(self, options, monitor=None, output=None):
        from .direct_voice import create_worker_process
        self.options = start_options('converted', options)
        self.monitor = parse_monitor(monitor)
        self.output = output
        # A device route has no OS gate, so mute travels this channel as well.
        self._controlled = self.monitor is not None or output is not None
        self._router_seen = output is None
        for key in ('runtime', 'reference', 'model', 'index'):
            if self.options.get(key):
                self.options[key] = str(Path(self.options[key]).expanduser().resolve())
        create_worker_process(self.options)  # Existing local path checks; no capture/model load.
        self._state = dict(BASE_STATE)
        self._lock, self._stop = Lock(), Event()
        self._thread = self._child = self._stdin = None
        self._cleanup_ok = True
        self._monitor_muted = True
        self._direct_suppressed = False
        self._monitor_revision = 0
        self._sent_monitor_revision = 0
        self._monitor_pending_since = None
        # Every frame to the router, in order and whole: a speech frame does not fit a
        # pipe's atomic write, so controls queue behind it instead of cutting into it.
        self._out = bytearray()

    def set_monitor_muted(self, muted):
        # Receiver/gate fast path: never write a pipe or wait for the router here.
        with self._lock:
            if self._monitor_muted != bool(muted):
                self._monitor_muted = bool(muted)
                # Without a monitor or device the OS gate mutes; the router needs no frame.
                if self._controlled:
                    self._monitor_revision += 1

    def set_direct_suppressed(self, suppressed):
        """Silence the microphone's blocks only; converted speech still plays (ADR-007)."""
        with self._lock:
            if self._direct_suppressed != bool(suppressed):
                self._direct_suppressed = bool(suppressed)
                self._monitor_revision += 1

    def _monitor_control(self):
        return dict(kind='monitor_mute', muted=self._monitor_muted, suppressed=self._direct_suppressed,
                    revision=self._monitor_revision)

    def speak(self, chunks, token, on_first_audio=None):
        """Send speech (an iterable of 48 kHz mono s16le bytes) to be converted, in real time.

        Speech is sent as it arrives, at most SPEECH_LEAD_NS ahead of what the router
        plays. Returns once all of it has had time to play, or raises when the token or this
        owner stops; then the router drops what it still holds.
        """
        start = None
        sent_ns = 0

        def send(chunk):
            nonlocal start, sent_ns
            if start is None:
                start = time.monotonic_ns()
            while time.monotonic_ns() - start < sent_ns - SPEECH_LEAD_NS:
                self._speech_check(token)
                time.sleep(.01)
            self._speech_check(token)
            with self._lock:
                self._out.extend(speech_frame(chunk))
            if sent_ns == 0 and on_first_audio is not None:
                on_first_audio(time.monotonic_ns(), 48000)
            sent_ns += len(chunk) * 1_000_000_000 // (2 * 48000)

        try:
            pending = bytearray()
            for data in chunks:
                self._speech_check(token)
                pending.extend(data)
                while len(pending) >= SPEECH_FRAME:
                    send(bytes(pending[:SPEECH_FRAME]))
                    del pending[:SPEECH_FRAME]
            if len(pending) >= 2:
                send(bytes(pending[:len(pending) - len(pending) % 2]))
            with self._lock:
                self._out.extend(encode(dict(kind='speech_end')))
            # The conversion adds a block or two; wait them out so the next speech follows.
            while start is not None and time.monotonic_ns() - start < sent_ns + SPEECH_TAIL_NS:
                self._speech_check(token)
                time.sleep(.01)
        except BaseException:
            with self._lock:
                self._out.extend(encode(dict(kind='speech_cancel')))
            raise

    def _speech_check(self, token):
        token.check()
        with self._lock:
            if self._stop.is_set() or not self._state.get('active'):
                raise RuntimeError('vc_speech_unavailable')

    def speaking_available(self):
        with self._lock:
            return bool(self._state.get('active')) and not self._stop.is_set()

    def start(self, *, source):
        _validate(source, 'mic')
        request = dict(kind='start', source=_source_id(source), options=self.options)
        with self._lock:
            if self._thread is not None or self._stop.is_set():
                raise RuntimeError('vc_single_use')
            if self.monitor is not None:
                request.update(monitor=self.monitor)
            if self.output is not None:
                request.update(output=self.output)
            # The direct-voice suppression travels here on every route.
            if self._controlled or self._direct_suppressed:
                request.update(monitor_control=self._monitor_control())
            self._sent_monitor_revision = self._monitor_revision
            request = encode(request)
            self._state.update(requested=True, pending=True, state='preparing')
            self._thread = Thread(target=self._run, args=(request, source), name='vrct-vc-owner', daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._stop.set()
            self._state.update(requested=False, active=False, conversion_verified=False)

    def close(self, timeout=3):
        self.stop()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)
        return (thread is None or not thread.is_alive()) and self._cleanup_ok

    def health(self):
        with self._lock:
            return dict(self._state, stopping=bool(self._thread and self._thread.is_alive()
                                                   and self._stop.is_set()))

    def _check(self):
        if self._stop.is_set():
            raise RuntimeError('cancelled')

    def _check_control(self):
        self._check()
        now = time.monotonic()
        with self._lock:
            if self._monitor_revision != self._sent_monitor_revision:
                if self._monitor_pending_since is None:
                    self._monitor_pending_since = now
                self._out.extend(encode(self._monitor_control()))
                self._sent_monitor_revision = self._monitor_revision
            if self._out:
                try:
                    count = self._stdin.write(bytes(self._out))
                    if count is None or count <= 0:
                        raise OSError('vc_router_failed')
                    del self._out[:count]
                except BlockingIOError:
                    pass
            limit = 1 if self._router_seen else OWNED_ROUTER_START
            if self._monitor_pending_since is not None and now - self._monitor_pending_since >= limit:
                raise TimeoutError('vc_router_timeout')

    def _run(self, request, source):
        child = None
        try:
            self._check()
            child = self._child = _launch(source) if self.output is None else _launch(source, self.output)
            self._stdin = PipeWriter(child.stdin)
            pending, deadline = memoryview(request), time.monotonic()+5
            while pending:
                self._check()
                if time.monotonic() >= deadline:
                    raise TimeoutError('vc_router_timeout')
                if self._stdin.wait(.02):
                    try:
                        count = self._stdin.write(pending)
                        if count <= 0:
                            raise EOFError
                        pending = pending[count:]
                    except BlockingIOError:
                        pass
            reader = Reader(child.stdout)
            if self._controlled:
                self._monitor_pending_since = time.monotonic()
            while True:
                state = validate_health(reader.read(timeout=1 if self._router_seen else OWNED_ROUTER_START,
                                                    check=self._check_control))
                self._router_seen = True
                with self._lock:
                    self._check()
                    if state['monitor_revision'] > self._sent_monitor_revision:
                        raise ValueError('vc_router_health_invalid')
                    if state['monitor_revision'] == self._sent_monitor_revision == self._monitor_revision:
                        self._monitor_pending_since = None
                    self._state.update(state)
                if state['error']:
                    break
        except Exception as exc:
            with self._lock:
                if not self._stop.is_set() and not self._state['error']:
                    self._state['error'] = ('vc_router_timeout' if isinstance(exc, TimeoutError)
                                            else 'vc_router_failed')
        finally:
            cancelled = self._stop.is_set()
            self.stop()
            if child is not None:
                try:
                    # A write still in progress would hold this close on Windows.
                    if self._stdin is not None and not self._stdin.flush(.2):
                        child.terminate()
                    if self._stdin is not None:
                        self._stdin.close()
                    child.stdin.close()  # EOF requests cooperative audio cleanup.
                    try:
                        result = child.wait(timeout=2.2)
                        if result == 2:
                            self._cleanup_ok = False
                        if result and not cancelled and not self._state['error']:
                            self._state['error'] = 'vc_router_failed'
                    except subprocess.TimeoutExpired:
                        self._cleanup_ok = False
                        child.terminate()
                        try:
                            child.wait(timeout=.3)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(timeout=.3)
                    child.stdout.close()
                except Exception:
                    self._cleanup_ok = False
                finally:
                    feed = getattr(child, 'graph_feed', None)
                    if feed is not None:
                        feed.close()
            with self._lock:
                self._state.update(pending=False, active=False, requested=False,
                                   state='failed' if self._state['error'] else 'stopped')
                if not self._cleanup_ok:
                    self._state['error'] = self._state['error'] or 'vc_cleanup_failed'
