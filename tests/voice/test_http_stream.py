"""Cancellation must not depend on shutdown waking the OS receive wait."""
import http.client
import socket
from threading import Thread
from time import monotonic, sleep

import pytest


def test_polling_cancellation_interrupts_headers_without_native_shutdown(pcm_server):
    from models.http_stream import InterruptibleSocket

    class NoWakeSocket:
        def __init__(self, sock):
            self.sock = sock

        def shutdown(self, how):
            pass  # Reproduce Winsock's pending timeout-mode receive wait.

        def __getattr__(self, name):
            return getattr(self.sock, name)

    with pcm_server(before_get=lambda _: sleep(.3)) as (url, _):
        connection = http.client.HTTPConnection(url.split('//')[1], timeout=2)
        connection.connect()
        connection.sock = wrapped = InterruptibleSocket(NoWakeSocket(connection.sock))
        connection.request('GET', '/health')
        result = []
        def read():
            try:
                connection.getresponse()
            except OSError:
                result.append('interrupted')
        worker = Thread(target=read)
        worker.start()
        sleep(.04)
        start = monotonic()
        wrapped.shutdown(socket.SHUT_RDWR)
        worker.join(.2)
        try:
            assert not worker.is_alive()
            assert result == ['interrupted']
            assert monotonic() - start < .2
        finally:
            worker.join(2)
            connection.close()


def test_poll_timeouts_do_not_poison_http_buffer(pcm_server):
    from models.http_stream import InterruptibleSocket
    with pcm_server(before_get=lambda _: sleep(.08)) as (url, _):
        connection = http.client.HTTPConnection(url.split('//')[1], timeout=.5)
        connection.connect()
        connection.sock = InterruptibleSocket(connection.sock)
        try:
            connection.request('GET', '/health')
            response = connection.getresponse()
            assert response.read() == b'{"status":"ok"}'
            assert connection.sock.gettimeout() == .5
        finally:
            connection.close()


def test_receive_keeps_original_timeout():
    from models.http_stream import InterruptibleSocket
    left, right = socket.socketpair()
    left.settimeout(.06)
    wrapped = InterruptibleSocket(left)
    start = monotonic()
    try:
        with pytest.raises(TimeoutError):
            wrapped.recv_into(bytearray(10))
        assert .04 <= monotonic() - start < .3
        assert left.gettimeout() == .06
    finally:
        left.close()
        right.close()
