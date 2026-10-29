"""Model-free tests independent of src-python's Windows runtime conftest."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest


@pytest.fixture
def pcm_server():
    @contextmanager
    def start(*, chunks=(b"\x01", b"\x00\x02", b"\x00"), status=200,
              content_type="audio/pcm", rate="48000", before_chunk=None, before_headers=None,
              headers=None, truncate=False, health_status=200, health_body=b'{"status":"ok"}'):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                self.send_response(health_status if self.path == '/health' else 404)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(health_body)))
                self.end_headers()
                self.wfile.write(health_body)

            def do_POST(self):
                requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                try:
                    if before_headers:
                        before_headers()
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    if rate is not None:
                        self.send_header("X-Sample-Rate", rate)
                    self.send_header("Transfer-Encoding", "chunked")
                    for key, value in (headers or {}).items():
                        self.send_header(key, value)
                    self.end_headers()
                    for i, chunk in enumerate(chunks):
                        if before_chunk:
                            before_chunk(i)
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                        self.wfile.flush()
                    if truncate:
                        self.close_connection = True
                        return
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                except (ConnectionError, OSError):
                    pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)
    return start
