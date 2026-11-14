"""Stop and malformed control take priority over unconsumed health output."""
import os
from threading import Event, Thread
from types import SimpleNamespace
import sys

import pytest

from models.voice_conversion import router_worker as worker
from models.voice_conversion.router_protocol import BASE_STATE, encode

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux isolated transport')


@pytest.mark.parametrize('fault', ['health_full', 'extra_control'])
def test_router_stops_even_when_health_is_not_drained(monkeypatch, fault):
    import fcntl
    read, write = os.pipe()
    output_read, output_write = os.pipe()
    started, closed = Event(), Event()
    class Process:
        def start(self, **kwargs):
            started.set()
        def health(self):
            return dict(BASE_STATE, requested=True, active=True, state='ready')
        def set_direct_suppressed(self, suppressed):
            pass
        def close(self, timeout):
            closed.set()
            return True
    monkeypatch.setattr(worker, 'create_worker_process', lambda options: Process())
    incoming, outgoing = os.fdopen(read, 'rb', buffering=0), os.fdopen(output_write, 'wb', buffering=0)
    monkeypatch.setattr(worker, 'sys', SimpleNamespace(stdin=SimpleNamespace(buffer=incoming, fileno=incoming.fileno),
                                                     stdout=SimpleNamespace(buffer=outgoing, fileno=outgoing.fileno)))
    if fault == 'health_full':
        size = fcntl.fcntl(output_write, fcntl.F_SETPIPE_SZ, 4096)
        os.write(output_write, b'x'*size)
    request = dict(kind='start', source=dict(cookie='1', serial='2', name='test.source', media_class='Audio/Source'),
                   options=dict(runtime='/seed', reference='/ref.wav'))
    os.write(write, encode(request)+(b'garbage\n' if fault == 'extra_control' else b''))
    results = []
    thread = Thread(target=lambda: results.append(worker.main()), daemon=True)
    thread.start()
    try:
        if fault == 'health_full':
            assert started.wait(1)
            os.close(write)
            write = None
            assert closed.wait(.5), 'health backpressure prevented Stop'
        else:
            thread.join(.5)
            assert results == [1] and not started.is_set(), 'extra control started capture'
    finally:
        if write is not None:
            os.close(write)
        os.set_blocking(output_read, False)
        try:
            os.read(output_read, 65536)
        except BlockingIOError:
            pass
        thread.join(1)
        incoming.close()
        outgoing.close()
        os.close(output_read)
        assert not thread.is_alive()


def test_router_hands_speech_and_suppression_to_the_conversion(monkeypatch):
    """Speech through the conversion (ADR-007): frames in order, then Stop by EOF."""
    from models.voice_conversion.router_protocol import speech_frame
    read, write = os.pipe()
    output_read, output_write = os.pipe()
    calls, closed = [], Event()
    class Process:
        def start(self, **kwargs):
            calls.append('start')
        def health(self):
            return dict(BASE_STATE, requested=True, active=True, state='ready')
        def set_direct_suppressed(self, suppressed):
            calls.append(('suppressed', suppressed))
        def speech_chunk(self, pcm):
            calls.append(('speech', len(pcm)))
            return True
        def speech_end(self):
            calls.append('end')
        def speech_cancel(self):
            calls.append('cancel')
        def close(self, timeout):
            closed.set()
            return True
    monkeypatch.setattr(worker, 'create_worker_process', lambda options: Process())
    incoming, outgoing = os.fdopen(read, 'rb', buffering=0), os.fdopen(output_write, 'wb', buffering=0)
    monkeypatch.setattr(worker, 'sys', SimpleNamespace(stdin=SimpleNamespace(buffer=incoming, fileno=incoming.fileno),
                                                     stdout=SimpleNamespace(buffer=outgoing, fileno=outgoing.fileno)))
    request = dict(kind='start', source=dict(cookie='1', serial='2', name='test.source', media_class='Audio/Source'),
                   options=dict(runtime='/seed', reference='/ref.wav'),
                   monitor_control=dict(kind='monitor_mute', muted=True, suppressed=True, revision=0))
    os.write(write, encode(request))
    results = []
    thread = Thread(target=lambda: results.append(worker.main()), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if 'start' in calls:
                break
            Event().wait(.02)
        os.write(write, speech_frame(b'\1\0' * 3840) + speech_frame(b'\2\0' * 100) + encode(dict(kind='speech_end'))
                 + encode(dict(kind='speech_cancel'))
                 + encode(dict(kind='monitor_mute', muted=True, suppressed=False, revision=1)))
        for _ in range(100):
            if ('suppressed', False) in calls:
                break
            Event().wait(.02)
        os.close(write)
        write = None
        assert closed.wait(1)
        thread.join(1)
        assert results == [0]
        assert calls == [('suppressed', True), 'start', ('speech', 7680), ('speech', 200), 'end', 'cancel',
                         ('suppressed', False)]
    finally:
        if write is not None:
            os.close(write)
        os.set_blocking(output_read, False)
        try:
            os.read(output_read, 65536)
        except BlockingIOError:
            pass
        thread.join(1)
        incoming.close()
        outgoing.close()
        os.close(output_read)