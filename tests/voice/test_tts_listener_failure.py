"""A stopped listener must interrupt playback even with unread HTTP PCM."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
from threading import Event, Thread, enumerate as threads
from time import monotonic, sleep

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.tts.settings import VoiceSettings
from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS, SpeechError
from models.tts.tts_scheduler import VoiceEventBus
from models.voice_events import SpeechMessageEvent


PCM = b'\x01\x00' * 48000 * 4


@contextmanager
def buffered_server(host='127.0.0.1', pcm=PCM):
    """Real TCP backlog; closing the listener leaves the response socket alive."""
    sent, finish = Event(), Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'audio/pcm')
                self.send_header('X-Sample-Rate', '48000')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                self.wfile.write(f'{len(pcm):x}\r\n'.encode() + pcm + b'\r\n')
                self.wfile.flush()
                sent.set()
                finish.wait(5)
                self.wfile.write(b'0\r\n\r\n')
                self.wfile.flush()
            except (OSError, ConnectionError):
                pass

        def log_message(self, *args):
            pass

    class Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if ':' in host else socket.AF_INET

    server = Server((host, 0), Handler)
    worker = Thread(target=lambda: server.serve_forever(poll_interval=.005), daemon=True)
    worker.start()

    def stop_listener():
        server.shutdown()
        server.server_close()
        worker.join(1)
        assert not worker.is_alive()

    try:
        address = f'[{host}]' if ':' in host else host
        yield f'http://{address}:{server.server_port}', sent, finish, stop_listener
    finally:
        finish.set()
        stop_listener()


@pytest.mark.parametrize('host', ['127.0.0.1', '::1'])
def test_listener_loss_cancels_without_consuming_buffered_pcm(host):
    with buffered_server(host) as (url, sent, _finish, stop):
        token = CancelToken()
        stream = SpeechCppTTS(url).synthesize_stream('test', 'none', 'ja', token)
        try:
            assert next(stream).pcm
            assert sent.wait(1)  # Four seconds queued, only one frame consumed.
            stop()
            assert token.wait(.5), 'server loss was hidden behind unread PCM'
            assert token.reason == 'server_unavailable'
            with pytest.raises(SpeechError, match='server_unavailable'):
                next(stream)
        finally:
            stream.close()


def test_server_loss_aborts_real_scheduler_output_instead_of_draining():
    writing = Event()
    closed = []

    class SlowOutput:
        def write(self, pcm, token):
            writing.set()
            token.wait(.02)
            token.check()

        def close(self, *, drain, token):
            closed.append(drain)

    with buffered_server() as (url, sent, _finish, stop):
        bus = VoiceEventBus(VoiceSettings(mode='original', output_device='test', japanese_url=url),
                            router=AudioRouter(lambda *args: SlowOutput()))
        try:
            assert bus.publish(SpeechMessageEvent('fault', 'chat', 'test', source_language='ja'))
            assert writing.wait(1) and sent.wait(1)
            stop()
            deadline = monotonic() + .5
            while bus.status()['active'] and monotonic() < deadline:
                sleep(.005)
            state = bus.status()
            assert not state['active'], 'playback continued draining the dead server'
            assert state['errors'] == 1 and state['cancelled'] == 0
            assert state['last_error'] == 'server_unavailable'
            assert closed == [False]
        finally:
            assert bus.close()


def test_slow_consumer_does_not_truncate_healthy_server_audio():
    with buffered_server() as (url, sent, finish, _stop):
        token = CancelToken()
        stream = SpeechCppTTS(url, timeout=.05).synthesize_stream('test', 'none', 'ja', token)
        try:
            first = next(stream).pcm
            assert sent.wait(1)
            assert not token.wait(.3)  # Playback wait is not an HTTP stall.
            finish.set()
            actual = first + b''.join(frame.pcm for frame in stream)
            assert actual == PCM
            assert not token.is_set()
        finally:
            stream.close()


def test_failed_server_does_not_cancel_an_independent_request():
    with buffered_server() as (url_a, sent_a, _finish_a, stop_a), \
            buffered_server() as (url_b, sent_b, finish_b, _stop_b):
        token_a, token_b = CancelToken(), CancelToken()
        stream_a = SpeechCppTTS(url_a).synthesize_stream('first', 'none', 'ja', token_a)
        stream_b = SpeechCppTTS(url_b).synthesize_stream('second', 'none', 'ja', token_b)
        try:
            assert next(stream_a).pcm
            first_b = next(stream_b).pcm
            assert sent_a.wait(1) and sent_b.wait(1)
            stop_a()
            assert token_a.wait(.5)
            assert not token_b.wait(.15)
            finish_b.set()
            assert first_b + b''.join(frame.pcm for frame in stream_b) == PCM
        finally:
            stream_a.close()
            stream_b.close()


@pytest.mark.parametrize('error', [TimeoutError, OSError])
def test_inconclusive_probe_does_not_cancel_valid_audio(monkeypatch, error):
    with buffered_server() as (url, sent, finish, _stop):
        token = CancelToken()
        stream = SpeechCppTTS(url).synthesize_stream('test', 'none', 'ja', token)
        attempted = Event()

        def fail_connect(*args, **kwargs):
            attempted.set()
            raise error('probe only: busy listener or local resource pressure')

        try:
            first = next(stream).pcm
            assert sent.wait(1)
            # Only the additional connect syscall is fault-injected. The speech
            # HTTP connection and all PCM parsing remain real.
            monkeypatch.setattr(socket, 'create_connection', fail_connect)
            assert attempted.wait(.5)
            assert not token.wait(.1)
            finish.set()
            assert first + b''.join(frame.pcm for frame in stream) == PCM
        finally:
            stream.close()


@pytest.mark.parametrize('ending', ['closed', 'complete', 'cancelled'])
def test_request_end_releases_monitor_and_prevents_late_cancellation(ending):
    before = set(threads())
    with buffered_server() as (url, sent, finish, stop):
        token = CancelToken()
        stream = SpeechCppTTS(url).synthesize_stream('test', 'none', 'ja', token)
        try:
            assert next(stream).pcm
            assert sent.wait(1)
            if ending == 'complete':
                finish.set()
                list(stream)
            elif ending == 'cancelled':
                token.cancel()
                with pytest.raises(SpeechError, match='cancelled'):
                    next(stream)
            stream.close()
            stop()
            if ending == 'cancelled':
                assert token.reason == 'cancelled'
            else:
                assert not token.wait(.15), 'an ended request was cancelled by a stale monitor'
            assert not [t for t in threads() if t not in before and t.name == 'vrct-tts-listener']
        finally:
            stream.close()


@pytest.mark.parametrize('host,listener_ip', [('127.0.0.1', '127.0.0.1'),
    ('127.0.0.1', '0.0.0.0'), ('127.0.0.1', '::'), ('::1', '::1'), ('::1', '::'),
    ('localhost', '127.0.0.1'), ('localhost', '::1')])
def test_windows_listener_table_requires_exact_port_and_listen_state(monkeypatch, host, listener_ip):
    import psutil
    from types import SimpleNamespace
    from models.tts.speechcpp_tts import _windows_listener_missing
    rows = [SimpleNamespace(status=psutil.CONN_LISTEN, laddr=(listener_ip, 1234))]
    monkeypatch.setattr(psutil, 'net_connections', lambda kind: rows)
    assert not _windows_listener_missing((host, 1234))
    assert _windows_listener_missing((host, 1235))
    rows[0].status = psutil.CONN_ESTABLISHED
    assert _windows_listener_missing((host, 1234))
    rows[0].status, rows[0].laddr = psutil.CONN_LISTEN, ('192.0.2.1', 1234)
    assert _windows_listener_missing((host, 1234))


def test_windows_listener_query_failure_is_inconclusive(monkeypatch):
    import psutil
    from models.tts.speechcpp_tts import _windows_listener_missing
    def unavailable(**kwargs):
        raise psutil.AccessDenied()
    monkeypatch.setattr(psutil, 'net_connections', unavailable)
    assert not _windows_listener_missing(('127.0.0.1', 1234))
