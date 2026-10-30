"""One direct producer at a time, independently of ASR, TTS and global mute.

Backend factories, start(), stop() and health() must be nonblocking. Slow model
loading belongs to a backend-owned thread/process; close(timeout) reaps it.
The owner never interprets endpoint connectivity as proof of conversion.
"""
from copy import deepcopy
from threading import Lock
import time

from models.audio_routing.source_bridge import Endpoint, SourceBridge, _source_id, parse_source


def create_converted_process(options):
    from .isolated import IsolatedVCProcess
    return IsolatedVCProcess(options)


def create_worker_process(options):
    # Linux-only optional backend is loaded only after an explicit converted Start.
    from .settings import start_options
    options = start_options('converted', options)
    if options.get('engine') == 'rvc':
        from .rvc_process import RVCProcess
        return RVCProcess(options)
    from .seed_process import SeedProcess
    return SeedProcess(options)


class DirectVoice:
    def __init__(self, *, passthrough_factory=SourceBridge, converted_factory=None):
        self._original = passthrough_factory
        self._converted = converted_factory
        self._lock = Lock()
        self._backend = None
        self._source = None
        self._mode = 'off'
        self._options = {}
        self._generation = self._observation = 0
        self._requested = self._closed = False
        self._error = None

    def start(self, *, source, expected_generation, mode='passthrough', options=None):
        if not isinstance(source, Endpoint):
            raise ValueError('source_bridge_source_invalid')
        parse_source(_source_id(source))
        if (mode not in ('passthrough', 'converted') or type(expected_generation) is not int
                or (options is not None and not isinstance(options, dict))
                or (mode == 'passthrough' and options)):
            raise ValueError('vc_request_invalid')
        choices = deepcopy(options or {})
        with self._lock:
            if self._closed:
                raise RuntimeError('source_bridge_closed')
            if expected_generation != self._generation:
                raise RuntimeError('source_bridge_stale_start')
            if self._requested:
                if (self._source, self._mode, self._options) == (source, mode, choices):
                    return
                raise RuntimeError('vc_stop_required')
            if mode == 'converted' and self._converted is None:
                raise RuntimeError('vc_engine_unavailable')
            if self._backend is not None:
                if not self._backend.close(timeout=0):
                    raise RuntimeError('source_bridge_stopping')
                self._backend = None
            self._generation += 1
            self._source, self._mode, self._options = source, mode, choices
            self._error = None
            try:
                self._backend = (self._original() if mode == 'passthrough'
                                 else self._converted(deepcopy(choices)))
                self._requested = True
                self._backend.start(source=source)
            except Exception:
                self._requested = False
                self._error = 'vc_start_failed'
                if self._backend is not None:
                    self._backend.stop()
                raise RuntimeError('vc_start_failed') from None

    def _stop_locked(self):
        self._requested = False
        self._generation += 1
        if self._backend is not None:
            self._backend.stop()

    def stop(self):
        with self._lock:
            self._stop_locked()

    def close(self, timeout=3):
        with self._lock:
            self._closed = True
            self._stop_locked()
            backend = self._backend
        return backend is None or backend.close(timeout=timeout)

    def health(self):
        with self._lock:
            state = self._backend.health() if self._backend is not None else {}
            if self._requested and (not state.get('requested') or state.get('error')):
                self._error = state.get('error')
                self._stop_locked()
                state = self._backend.health()
            self._observation = max(time.monotonic_ns(), self._observation + 1)
            return dict(
                requested=self._requested,
                active=self._requested and bool(state.get('active')),
                pending=bool(state.get('pending') or state.get('stopping')),
                stopping=bool(state.get('stopping')),
                mode=self._mode if self._requested else 'off',
                source=_source_id(self._source) if self._source else None,
                generation=self._generation, observation_id=str(self._observation),
                error=self._error or state.get('error'),
                conversion_state=(state.get('state') if self._requested and self._mode == 'converted' else None),
                conversion_verified=(self._requested and self._mode == 'converted'
                                     and bool(state.get('conversion_verified'))),
            )
