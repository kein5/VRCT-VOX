"""A stuck OS table query cannot block playback cleanup or grow worker count."""
from threading import Event, Thread
from time import monotonic


def test_stalled_query_is_bounded_shared_and_does_not_reuse_stale_result():
    from models.tts.listener_table import ListenerTableProbe
    entered, release, next_entered, next_release = Event(), Event(), Event(), Event()
    calls = []
    def query():
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            release.wait(2)
            return ['old']
        next_entered.set()
        next_release.wait(2)
        return ['fresh']
    probe = ListenerTableProbe(query)
    try:
        start = monotonic()
        assert probe.read(Event(), timeout=.03) is None
        assert entered.is_set()
        worker = probe._worker
        for _ in range(3):
            assert probe.read(Event(), timeout=.02) is None
            assert probe._worker is worker
        assert len(calls) == 1 and monotonic() - start < .3
        results = []
        waiter = Thread(target=lambda: results.append(probe.read(Event(), timeout=.5)))
        waiter.start()
        release.set()
        assert next_entered.wait(.2)
        assert not results  # Completion of the old request is not current evidence.
        next_release.set()
        waiter.join(.5)
        assert results == [['fresh']]
    finally:
        release.set()
        next_release.set()
        assert probe.close(.5)


def test_stop_does_not_wait_for_os_query():
    from models.tts.listener_table import ListenerTableProbe
    entered, release, stopped = Event(), Event(), Event()
    def query():
        entered.set()
        release.wait(2)
        return []
    probe = ListenerTableProbe(query)
    values = []
    waiter = Thread(target=lambda: values.append(probe.read(stopped, timeout=1)))
    waiter.start()
    try:
        assert entered.wait(.2)
        stopped.set()
        waiter.join(.2)
        assert values == [None] and not waiter.is_alive()
        assert not probe.close(.02)  # Report unreaped native call; never claim success.
    finally:
        release.set()
        assert probe.close(.5)


def test_query_failure_is_inconclusive_and_retryable():
    from models.tts.listener_table import ListenerTableProbe
    calls = []
    def query():
        calls.append(1)
        if len(calls) == 1:
            raise OSError('unavailable')
        return []
    probe = ListenerTableProbe(query)
    try:
        assert probe.read(Event()) is None
        assert probe.read(Event()) == []
    finally:
        assert probe.close(.5)
