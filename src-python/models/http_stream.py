"""Keep HTTP's buffered parser while bounding cancellation of socket reads."""
import socket
from threading import Event
from time import monotonic


class InterruptibleSocket:
    """A connected socket whose receive wait checks shutdown every 20 ms.

    Winsock shutdown need not wake CPython's timeout-mode select immediately.
    Short internal timeouts stay below SocketIO so they do not poison its
    buffered reader. The caller's original timeout still bounds each receive.
    One worker owns reads and final close; cancellation only signals shutdown.
    """
    def __init__(self, sock):
        self._socket = sock
        self._interrupted = Event()

    def __getattr__(self, name):
        return getattr(self._socket, name)

    def shutdown(self, how):
        if how in (socket.SHUT_RD, socket.SHUT_RDWR):
            self._interrupted.set()
        return self._socket.shutdown(how)

    def recv_into(self, buffer, *args):
        timeout = self._socket.gettimeout()
        deadline = None if timeout is None else monotonic() + timeout
        try:
            while True:
                if self._interrupted.is_set():
                    raise OSError('http_stream_interrupted')
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError('timed out')
                self._socket.settimeout(.02 if remaining is None else min(.02, remaining))
                try:
                    return self._socket.recv_into(buffer, *args)
                except TimeoutError:
                    continue
        finally:
            self._socket.settimeout(timeout)

    def makefile(self, mode='r', buffering=None, **kwargs):
        stream = self._socket.makefile(mode, buffering, **kwargs)
        raw = getattr(stream, 'raw', stream)
        # CPython HTTPResponse consumes SocketIO through BufferedReader. Keep
        # that exact buffer, including any bytes already read after the headers.
        raw._sock = self
        return stream
