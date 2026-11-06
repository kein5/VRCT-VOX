"""One shared daemon worker isolates potentially slow native listener queries."""
from threading import Condition, Thread
from time import monotonic


class ListenerTableProbe:
    def __init__(self, query, *, freshness=.02):
        self._query = query
        self._condition = Condition()
        self._requested = self._completed = 0
        self._result = self._worker = None
        self._closed = False
        self._freshness = freshness
        self._result_at = self._started_at = None
        self._inflight = None

    def read(self, stopped, timeout=.05, *, not_before=None):
        """Reuse fresh rows, or require an observation begun at not_before."""
        deadline = monotonic() + timeout
        with self._condition:
            if self._closed or stopped.is_set():
                return None
            now = monotonic()
            fresh_after = now - self._freshness if not_before is None else not_before
            # Windows' monotonic() ticks every ~15.6 ms before Python 3.13, so an
            # older result can share this timestamp. Zero freshness never reuses,
            # and an observation required to begin at not_before must begin after
            # it: a query stamped with the same tick may have started earlier.
            reusable = not_before is not None or self._freshness > 0

            def fresh(at):
                return at is not None and (at > fresh_after if not_before is not None else at >= fresh_after)

            if reusable and self._result is not None and fresh(self._result_at):
                return self._result
            if self._inflight is not None and fresh(self._started_at):
                ticket = self._inflight
            else:
                self._requested += 1
                ticket = self._requested
            if self._worker is None:
                self._worker = Thread(target=self._run, name='vrct-listener-table', daemon=True)
                self._worker.start()
            self._condition.notify_all()
            while not self._closed and not stopped.is_set():
                if self._completed >= ticket:
                    return self._result
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(min(.01, remaining))
        return None

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._requested > self._completed)
                if self._closed:
                    return
                ticket = self._requested
                self._inflight, self._started_at = ticket, monotonic()
            try:
                result = self._query()
            except Exception:
                result = None
            with self._condition:
                self._result, self._completed = result, ticket
                # Age from query START: a slow native call must not renew stale
                # evidence for later readers merely because it just returned.
                self._result_at = self._started_at
                self._inflight = None
                self._condition.notify_all()

    def close(self, timeout=.05):
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._worker is not None:
            self._worker.join(timeout)
            return not self._worker.is_alive()
        return True


def _query_windows_table():
    import psutil
    return _listening_endpoints(psutil.net_connections(kind='tcp'), psutil)


def _listening_endpoints(rows, psutil):
    # Keep only local listening endpoints, never remote peers or process data.
    # Some Windows systems report a listening socket's state as 0, which psutil
    # calls NONE (seen on Windows 11 build 26220). Such a row without a remote
    # peer may be listening. Counting it only makes absence harder to prove, and
    # an unproven absence falls back to the ordinary request deadlines.
    return frozenset(tuple(row.laddr) for row in rows if row.laddr and (
        row.status == psutil.CONN_LISTEN or (row.status == psutil.CONN_NONE and not row.raddr)))


# Process-wide lifetime, not one worker per speech request. A hung native call
# occupies at most this one daemon thread; later requests time out and use the
# ordinary TCP probe/deadlines. It is never joined by playback cleanup.
windows_listener_table = ListenerTableProbe(_query_windows_table)
