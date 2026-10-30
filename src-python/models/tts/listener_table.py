"""One shared daemon worker isolates potentially slow native listener queries."""
from threading import Condition, Thread
from time import monotonic


class ListenerTableProbe:
    def __init__(self, query):
        self._query = query
        self._condition = Condition()
        self._requested = self._completed = 0
        self._result = self._worker = None
        self._closed = False

    def read(self, stopped, timeout=.05):
        deadline = monotonic() + timeout
        with self._condition:
            if self._closed or stopped.is_set():
                return None
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
            try:
                result = self._query()
            except Exception:
                result = None
            with self._condition:
                self._result, self._completed = result, ticket
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
    # Keep only local listening endpoints, never remote peers or process data.
    return frozenset(tuple(row.laddr) for row in psutil.net_connections(kind='tcp')
                     if row.status == psutil.CONN_LISTEN and row.laddr)


# Process-wide lifetime, not one worker per speech request. A hung native call
# occupies at most this one daemon thread; later requests time out and use the
# ordinary TCP probe/deadlines. It is never joined by playback cleanup.
windows_listener_table = ListenerTableProbe(_query_windows_table)
