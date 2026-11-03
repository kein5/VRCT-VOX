"""Listener lifetime and probe rates without sockets, processes or audio devices."""
from contextlib import nullcontext
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace

import pytest

from models.tts import listener_monitor, listener_table, speechcpp_tts as tts
from models.speech_server import runtime
from models.speech_server.low_latency import LowLatencyStandby


ADDRESS = ('127.0.0.1', 8080)


class FakeProcess:
    def __init__(self):
        self.exited, self.waiting = Event(), Event()
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        self.waiting.set()
        assert self.exited.wait(2)
        return 1

    def poll(self):
        return 1 if self.exited.is_set() else None


@pytest.fixture
def registry(monkeypatch):
    value = listener_monitor.ListenerMonitors()
    monkeypatch.setattr(tts, 'listener_monitors', value)
    monkeypatch.setattr(runtime, 'listener_monitors', value)
    monkeypatch.setattr(tts.sys, 'platform', 'linux')
    yield value
    for monitor in list(value.owners.values()):
        monitor.process.exited.set()
        monitor.thread.join(1)
        assert not monitor.thread.is_alive()
    for monitor in list(value.external.values()):
        for watch in tuple(monitor.watches):
            watch.close()
        monitor.thread.join(1)
        assert not monitor.thread.is_alive()


@pytest.fixture
def transport(monkeypatch):
    connections, probes = [], []

    class Connection:
        def __init__(self, *args, **kwargs):
            self.timeouts, self.shutdowns, self.reads = [], [], []
            self.closed = self.response_closed = False
            self.chunks = iter([b'\x01\x00' * 8, b'\x02\x00' * 8, b''])
            self.sock = SimpleNamespace(settimeout=self.timeouts.append,
                                        shutdown=self.shutdowns.append)
            connections.append(self)

        def connect(self):
            pass

        def request(self, *args):
            pass

        def getresponse(self):
            return SimpleNamespace(status=200, length=0, read1=self.read,
                                   getheader=lambda name, default='': {
                                       'Content-Type': 'audio/pcm', 'X-Sample-Rate': '48000'
                                   }.get(name, default), close=self.close_response)

        def read(self, size):
            self.reads.append(size)
            return next(self.chunks)

        def close_response(self):
            self.response_closed = True

        def close(self):
            self.closed = True

    def connect(address, timeout):
        probes.append((address, timeout))
        return nullcontext()

    monkeypatch.setattr(tts.http.client, 'HTTPConnection', Connection)
    monkeypatch.setattr(tts.socket, 'create_connection', connect)
    return connections, probes


def stream(token, port=8080):
    return tts.SpeechCppTTS(f'http://127.0.0.1:{port}').synthesize_stream(
        'test', 'none', 'ja', token)


@pytest.mark.parametrize('concurrent', [1, 2])
def test_owned_exit_interrupts_suspended_stream_without_connects(registry, transport, concurrent):
    process = FakeProcess()
    owner = registry.own(ADDRESS, process)
    tokens = [tts.CancelToken() for _ in range(concurrent)]
    other = tts.CancelToken()
    streams = [stream(token) for token in tokens]
    try:
        assert process.waiting.wait(.5)
        for active in streams:
            assert next(active).pcm
        assert all(len(connection.reads) == 1 for connection in transport[0])
        process.exited.set()
        for token, active in zip(tokens, streams):
            assert token.wait(.2)
            assert token.reason == 'server_unavailable'
            with pytest.raises(tts.SpeechError, match='server_unavailable'):
                next(active)
        assert not other.is_set()
        assert process.waits == [None]  # Blocking wait, no timeout/poll loop.
        assert not transport[1] and not registry.external
        assert all(connection.shutdowns == [tts.socket.SHUT_RDWR] for connection in transport[0])
    finally:
        for active in streams:
            active.close()
        owner.thread.join(.5)
    assert not owner.watches


def test_owned_exit_before_first_pcm_and_port_reuse_keep_process_identity(registry, transport):
    first, second = FakeProcess(), FakeProcess()
    old = registry.own(ADDRESS, first)
    token = tts.CancelToken()
    active = stream(token)
    connection_type = tts.http.client.HTTPConnection
    original = connection_type.connect

    def replace(connection):
        original(connection)
        first.exited.set()
        old.thread.join(.5)
        registry.own(ADDRESS, second)
        registry.forget(old)  # Late cleanup must not remove the replacement.

    connection_type.connect = replace
    try:
        with pytest.raises(tts.SpeechError, match='server_unavailable'):
            next(active)
        assert registry.owned(ADDRESS).process is second
        assert not transport[1]
    finally:
        active.close()


@pytest.mark.parametrize('ending', ['close', 'complete', 'cancel'])
def test_owned_request_end_detaches_without_waiting_for_process(registry, transport, ending):
    owner = registry.own(ADDRESS, FakeProcess())
    token = tts.CancelToken()
    active = stream(token)
    assert next(active).pcm
    if ending == 'complete':
        assert len(list(active)) == 1
    elif ending == 'cancel':
        token.cancel()
    start = monotonic()
    active.close()
    assert monotonic() - start < .2
    assert not owner.watches and owner.thread.is_alive()
    owner.process.exited.set()
    owner.thread.join(.5)
    assert token.is_set() == (ending == 'cancel')
    assert transport[0][0].closed and transport[0][0].response_closed
    assert not transport[1]


@pytest.mark.parametrize('error', [ConnectionRefusedError, TimeoutError, OSError])
def test_shared_probe_cancels_only_confirmed_address(registry, transport, monkeypatch, error):
    tokens = [tts.CancelToken() for _ in range(3)]
    streams = [stream(tokens[0]), stream(tokens[1]), stream(tokens[2], port=8081)]
    attempted = Event()

    def connect(address, timeout):
        assert timeout == .1
        if address == ADDRESS:
            attempted.set()
            raise error('fake connect failure')
        return nullcontext()

    try:
        for active in streams:
            assert next(active).pcm
        shared = registry.external[ADDRESS]
        assert len(shared.watches) == 2
        monkeypatch.setattr(tts.socket, 'create_connection', connect)
        assert attempted.wait(.5)
        if error is ConnectionRefusedError:
            assert tokens[0].wait(.2) and tokens[1].wait(.2)
            assert [token.reason for token in tokens[:2]] == ['server_unavailable'] * 2
        else:
            assert not tokens[0].wait(.06) and not tokens[1].is_set()
        assert not tokens[2].is_set()
        assert all(len(connection.reads) == 1 for connection in transport[0])
    finally:
        for active in streams:
            active.close()
    assert not registry.external


@pytest.mark.parametrize('ending', ['close', 'complete', 'cancel', 'stopped'])
def test_external_monitor_stops_only_after_last_subscription(registry, transport, ending):
    tokens = [tts.CancelToken(), tts.CancelToken()]
    streams = [stream(token) for token in tokens]
    for active in streams:
        assert next(active).pcm
    monitor = registry.external[ADDRESS]
    streams[0].close()
    assert monitor.thread.is_alive() and len(monitor.watches) == 1
    try:
        if ending == 'complete':
            list(streams[1])
        elif ending == 'cancel':
            tokens[1].cancel()
        elif ending == 'stopped':
            next(iter(monitor.watches))._stopped.set()
        else:
            streams[1].close()
        monitor.thread.join(.3)
        assert not monitor.thread.is_alive() and not registry.external
        assert not tokens[0].is_set()
        assert tokens[1].is_set() == (ending == 'cancel')
    finally:
        streams[1].close()


def test_stop_during_probe_prevents_late_cancellation_and_overlapping_probes(registry, monkeypatch):
    entered, release, second_entered, second_release = Event(), Event(), Event(), Event()
    calls = []

    def connect(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(1)
            raise ConnectionRefusedError()
        second_entered.set()
        assert second_release.wait(1)
        raise TimeoutError()

    monkeypatch.setattr(tts.socket, 'create_connection', connect)
    old_token, new_token = tts.CancelToken(), tts.CancelToken()
    stopped = Event()
    old = registry.watch(ADDRESS, old_token, stopped, tts._listener_missing)
    assert entered.wait(.5)
    new = None
    try:
        old.close()
        new = registry.watch(ADDRESS, new_token, Event(), tts._listener_missing)
        assert new._monitor is old._monitor and len(calls) == 1
        release.set()
        assert second_entered.wait(.5)
        # A new request must not receive the old request's in-flight observation.
        assert not old_token.is_set() and not new_token.is_set()
    finally:
        old.close()
        if new is not None:
            new.close()
        release.set()
        second_release.set()
        old.join()
    assert not old_token.is_set() and not new_token.is_set()
    assert not registry.external


def test_runtime_registers_owner_before_standby_uses_synthesis(registry, transport, monkeypatch):
    process = FakeProcess()
    server = runtime.SpeechServer('japanese', {'low_latency': True})
    server._child = process
    document = {'data': [{'speech': {'task': 'synthesis',
                                     'architecture': 'irodori-tts', 'device': 'Vulkan0'}}]}
    monkeypatch.setattr(runtime, '_json', lambda port, path, deadline:
                        {'status': 'ok'} if path == '/health' else document)
    monkeypatch.setattr(tts.SpeechCppTTS, 'get_model_options', lambda *args:
                        {'seed': {'minimum': 0, 'maximum': 100}, 'instructions': False})
    started = []

    def start(standby):
        assert registry.owned(ADDRESS).process is process
        token = tts.CancelToken()
        active = standby._synthesize(token)
        assert next(active).pcm
        started.append((token, active))

    monkeypatch.setattr(LowLatencyStandby, 'start', start)
    server._ready(8080, monotonic() + 1)
    try:
        assert server.health()['state'] == 'ready'
        assert len(started) == 1 and not transport[1]
        process.exited.set()
        assert started[0][0].wait(.2)
        assert started[0][0].reason == 'server_unavailable'
    finally:
        for _, active in started:
            active.close()


def test_http_first_audio_and_chunk_timeouts_are_unchanged(registry, transport, monkeypatch):
    monkeypatch.setattr(tts, 'monotonic', lambda: 10)
    active = tts.SpeechCppTTS('http://127.0.0.1:8080', timeout=.3,
                             first_audio_timeout=7).synthesize_stream('x', 'none', 'ja', tts.CancelToken())
    try:
        next(active)
        assert transport[0][0].timeouts == [7, 7, .3]
    finally:
        active.close()


def test_header_time_counts_against_first_audio_deadline(registry, transport, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(tts, 'monotonic', lambda: clock[0])
    connection_type = tts.http.client.HTTPConnection
    original = connection_type.getresponse

    def headers(connection):
        clock[0] += 8
        return original(connection)

    monkeypatch.setattr(connection_type, 'getresponse', headers)
    active = tts.SpeechCppTTS('http://127.0.0.1:8080', first_audio_timeout=7).synthesize_stream(
        'x', 'none', 'ja', tts.CancelToken())
    with pytest.raises(tts.SpeechError, match='first_audio_timeout'):
        next(active)
    assert not registry.external and not transport[1]
    assert not transport[0][0].reads and transport[0][0].closed


def test_chunk_timeout_keeps_diagnostic_and_releases_monitor(registry, transport, monkeypatch):
    connection_type = tts.http.client.HTTPConnection
    original = connection_type.read

    def read(connection, size):
        if connection.reads:
            raise TimeoutError()
        return original(connection, size)

    monkeypatch.setattr(connection_type, 'read', read)
    token = tts.CancelToken()
    active = stream(token)
    assert next(active).pcm
    with pytest.raises(tts.SpeechError, match='transport_error'):
        next(active)
    assert not registry.external and not token.is_set()
    assert transport[0][0].closed


@pytest.mark.parametrize('concurrent', [1, 2])
@pytest.mark.parametrize('owned', [False, True])
def test_one_second_probe_counts_before_and_after(registry, transport, monkeypatch, concurrent, owned):
    class DeferredThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    class ClockStop:
        def __init__(self):
            self.elapsed, self.stopped = 0, False

        def wait(self, seconds):
            if not self.stopped:
                self.elapsed += seconds
            return self.stopped

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def clear(self):
            self.stopped = False

    # Reference: the former independent 20 ms loop, with zero-cost fake probes.
    before = []
    for _ in range(concurrent):
        clock = ClockStop()
        for _ in range(50):
            clock.wait(.02)
            before.append(ADDRESS)
        assert clock.elapsed == pytest.approx(1)
    monkeypatch.setattr(listener_monitor, 'Thread', DeferredThread)
    monkeypatch.setattr(listener_monitor, 'Event', ClockStop)
    watches = []
    after = []
    owner = registry.own(ADDRESS, FakeProcess()) if owned else None

    def probe(address, stopped):
        after.append(address)
        result = tts._listener_missing(address, stopped)
        if len(after) == 50:
            for watch in watches:
                watch.close()
        return result

    for _ in range(concurrent):
        watches.append(registry.watch(ADDRESS, tts.CancelToken(), Event(), probe, owner=owner))
    monitor = watches[0]._monitor
    if owned:
        monitor.stopped.elapsed = 1
        owner.process.exited.set()
        owner._wait()
        registry.forget(owner)
    else:
        monitor._run()
    assert monitor.stopped.elapsed == pytest.approx(1)
    assert len(before) == 50 * concurrent
    assert len(after) == len(transport[1]) == (0 if owned else 50)
    assert not registry.external
    print(f'fake 1 s, owned={owned}, streams={concurrent}: '
          f'before={len(before)}, after={len(after)} connects/s')


@pytest.mark.parametrize('rows', [None, frozenset(), frozenset([ADDRESS])])
def test_windows_monitor_distinguishes_absence_from_inconclusive_table(registry, monkeypatch, rows):
    tokens = [tts.CancelToken(), tts.CancelToken()]
    attempted = Event()
    connects = []

    def read(stopped, **kwargs):
        attempted.set()
        return rows

    def connect(*args, **kwargs):
        connects.append(1)
        raise TimeoutError()

    monkeypatch.setattr(tts.sys, 'platform', 'win32')
    monkeypatch.setattr(tts, 'windows_listener_table', SimpleNamespace(read=read))
    monkeypatch.setattr(tts.socket, 'create_connection', connect)
    watches = [registry.watch(ADDRESS, token, Event(), tts._listener_missing) for token in tokens]
    try:
        assert attempted.wait(.5)
        if rows == frozenset():
            assert all(token.wait(.2) for token in tokens)
            assert all(token.reason == 'server_unavailable' for token in tokens)
            assert not connects
        else:
            assert not tokens[0].wait(.05) and not tokens[1].is_set()
            assert bool(connects) == (rows is None)
    finally:
        for watch in watches:
            watch.close()
            watch.join()


def test_stopped_during_windows_table_read_skips_connect(registry, monkeypatch):
    stopped = Event()

    def read(probe_stopped, **kwargs):
        probe_stopped.set()
        return None

    monkeypatch.setattr(tts.sys, 'platform', 'win32')
    monkeypatch.setattr(tts, 'windows_listener_table', SimpleNamespace(read=read))
    monkeypatch.setattr(tts.socket, 'create_connection', lambda *args, **kwargs: pytest.fail('late probe'))
    assert not tts._listener_missing(ADDRESS, stopped)


def test_windows_table_cache_is_shared_expires_and_coalesces_inflight(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(listener_table, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(tts, 'monotonic', lambda: clock[0])
    entered, release = Event(), Event()
    calls = []

    def query():
        calls.append(1)
        entered.set()
        assert release.wait(1)
        return frozenset([ADDRESS])

    probe = listener_table.ListenerTableProbe(query)
    results = []
    first = Thread(target=lambda: results.append(probe.read(Event())))
    second = Thread(target=lambda: results.append(probe.read(Event())))
    try:
        first.start()
        assert entered.wait(.5)
        second.start()
        release.set()
        first.join(.5)
        second.join(.5)
        assert results == [frozenset([ADDRESS])] * 2 and len(calls) == 1
        monkeypatch.setattr(tts, 'windows_listener_table', probe)
        clock[0] += .019
        assert not tts._windows_listener_missing(ADDRESS)
        assert len(calls) == 1
        clock[0] += .002
        assert not tts._windows_listener_missing(ADDRESS)
        assert len(calls) == 2
        stopped = Event()
        stopped.set()
        assert probe.read(stopped) is None
    finally:
        release.set()
        first.join(.5)
        if second.ident is not None:
            second.join(.5)
        assert probe.close(.5)


def test_cached_absence_cannot_cancel_a_new_listener(monkeypatch):
    rows, calls = [], []

    def query():
        calls.append(1)
        return frozenset(rows)

    probe = listener_table.ListenerTableProbe(query)
    monkeypatch.setattr(tts, 'windows_listener_table', probe)
    try:
        assert probe.read(Event()) == frozenset()
        rows.append(ADDRESS)
        assert not tts._windows_listener_missing(ADDRESS)
        assert len(calls) == 2
    finally:
        assert probe.close(.5)


def test_absence_confirmation_shares_original_table_deadline(monkeypatch):
    clock, calls = [10.0], []

    def read(stopped, timeout=.05, **kwargs):
        calls.append(timeout)
        clock[0] += .04
        return frozenset() if len(calls) == 1 else None

    monkeypatch.setattr(tts, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(tts, 'windows_listener_table', SimpleNamespace(read=read))
    assert not tts._windows_listener_missing(ADDRESS)
    assert calls == pytest.approx([.05, .01])


def test_slow_table_completion_does_not_extend_cache_freshness(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(listener_table, 'monotonic', lambda: clock[0])
    calls = []

    def query():
        calls.append(1)
        clock[0] += .03
        return frozenset([ADDRESS])

    probe = listener_table.ListenerTableProbe(query)
    try:
        assert probe.read(Event()) == frozenset([ADDRESS])
        assert probe.read(Event()) == frozenset([ADDRESS])
        assert len(calls) == 2
    finally:
        assert probe.close(.5)
