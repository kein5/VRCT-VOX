"""Delayed router startup must not end the graph feed or publish its backlog."""
import ast
import json
import os
from pathlib import Path
import select
import sys
from threading import Event, Thread
import time
from types import SimpleNamespace

import pytest

from models.audio_routing import pipewire_graph as pg
from models.audio_routing import pipewire_graph_pipe as transport
import test_pipewire_graph as fixtures

shared = fixtures.shared
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux graph pipe')
NAMES = ('external.source', 'vrct.managed.vc')


@pytest.fixture
def small_pipe(monkeypatch):
    import fcntl
    pipe = os.pipe
    def create():
        read, write = pipe()
        fcntl.fcntl(write, fcntl.F_SETPIPE_SZ, 4096)
        return read, write
    monkeypatch.setattr(transport.os, 'pipe', create)


def frame(sequence, captured):
    wire = json.dumps(fixtures.graph()).encode()
    return transport._HEADER.pack(sequence, captured, len(wire)) + wire


@pytest.mark.parametrize('delay_before', ['receiver', 'first_read'])
def test_three_second_startup_delay_gets_fresh_graph(shared, small_pipe, monkeypatch, delay_before):
    source, backend = shared
    backend.data[1]['info']['props']['padding'] = 'x' * 14_000
    feed = transport.GraphFeed(NAMES)
    remote = None
    try:
        assert select.select([feed.read_fd], [], [], 1)[0]
        monkeypatch.setenv(transport._ENV, str(os.dup(feed.read_fd)))
        feed.close_reader()
        if delay_before == 'first_read':
            remote = transport.receive_from_parent()
            assert remote._thread is not None and remote._thread.is_alive()
        time.sleep(3)
        assert feed.thread.is_alive(), 'backpressure terminated the feed'
        if remote is None:
            remote = transport.receive_from_parent()
        with remote.subscribe():
            value = remote.read()
            assert value.sequence > 1
            assert 0 <= time.monotonic() - value.captured < pg.MAX_AGE
            assert len(value.data[1]['info']['props']['padding']) == 14_000
    finally:
        if remote is not None:
            remote.close()
        else:
            descriptor = os.environ.pop(transport._ENV, None)
            if descriptor is not None:
                os.close(int(descriptor))
        feed.close()
    assert source._thread is None


def test_never_reading_receiver_does_not_end_feed_and_close_is_prompt(shared, small_pipe, monkeypatch):
    source, backend = shared
    backend.data[1]['info']['props']['padding'] = 'x' * 14_000
    feed = transport.GraphFeed(NAMES)
    try:
        assert select.select([feed.read_fd], [], [], 1)[0]
        # Advance only the feed's clock past the old write deadline while its
        # first frame is partially written. The source continues refreshing.
        monkeypatch.setattr(transport, 'time', SimpleNamespace(monotonic=lambda: time.monotonic() + 3))
        time.sleep(.08)
        assert feed.thread.is_alive()
        started = time.monotonic()
        feed.close()
        assert time.monotonic() - started < .5
        assert not feed.thread.is_alive() and source._thread is None
    finally:
        feed.close()


def test_stale_backlog_is_not_published_and_initial_read_waits_for_fresh_frame():
    read, write = os.pipe()
    backlog_consumed, release, finished = Event(), Event(), Event()
    class PausedRemote(transport.RemoteGraph):
        reads = 0
        def _read(self, size):
            self.reads += 1
            if self.reads == 3:
                backlog_consumed.set()
                release.wait(.5)
            return super()._read(size)
    remote = PausedRemote(read)
    results, failures = [], []
    def acquire():
        try:
            results.append(remote.read())
        except pg.GraphUnavailable as exc:
            failures.append(exc)
        finally:
            finished.set()
    thread = Thread(target=acquire)
    try:
        with remote.subscribe():
            os.write(write, frame(1, time.monotonic() - 3))
            thread.start()
            assert backlog_consumed.wait(1)
            assert remote.observation() == pg.Observation(0, 0, None)
            assert not finished.wait(.02)
            os.write(write, frame(2, time.monotonic()))
            release.set()
            assert finished.wait(1)
            assert not failures and results[0].sequence == 2
            os.close(write)
            write = None
            fixtures.until(lambda: remote.observation().data is None)
            with pytest.raises(pg.GraphUnavailable):
                remote.read(wait=False)
    finally:
        release.set()
        remote.close()
        if thread.ident is not None:
            thread.join(1)
        if write is not None:
            os.close(write)


def test_child_exit_ends_backpressured_feed_and_releases_source(shared, small_pipe):
    source, backend = shared
    backend.data[1]['info']['props']['padding'] = 'x' * 14_000
    feed = transport.GraphFeed(NAMES)
    try:
        assert select.select([feed.read_fd], [], [], 1)[0]
        feed.close_reader()  # No receiver remains: the next write gets EPIPE.
        feed.thread.join(1)
        assert not feed.thread.is_alive() and source._thread is None
    finally:
        feed.close()


@pytest.mark.parametrize('entry', ['module', 'frozen'])
def test_receiver_starts_before_start_request_on_both_entries(shared, monkeypatch, entry):
    from models.voice_conversion import router_worker
    read, write = os.pipe()
    monkeypatch.setenv(transport._ENV, str(read))
    observed = []
    def reader(stream):
        remote = pg.graph_source()
        observed.append(remote)
        assert isinstance(remote, transport.RemoteGraph)
        assert remote._thread is not None and remote._thread.is_alive()
        raise EOFError('fake control closed before start')
    monkeypatch.setattr(router_worker, 'Reader', reader)
    if entry == 'module':
        path = Path(router_worker.__file__)
        namespace = dict(__name__='__main__', main=router_worker.main)
    else:
        path = Path(__file__).resolve().parents[1] / 'mainloop.py'
        namespace = dict(__name__='__main__', sys=SimpleNamespace(argv=['sidecar', '--voice-router-worker']))
    tree = ast.parse(path.read_text(encoding="utf-8"))
    dispatch = next(n for n in tree.body if isinstance(n, ast.If) and '__main__' in ast.unparse(n.test))
    try:
        with pytest.raises(SystemExit) as result:
            exec(compile(ast.Module(body=[dispatch], type_ignores=[]), str(path), 'exec'), namespace)
        assert result.value.code == 1 and len(observed) == 1
        assert observed[0]._thread is None and observed[0].fd is None
    finally:
        os.close(write)
        if isinstance(pg.graph_source(), transport.RemoteGraph):
            pg.graph_source().close()
