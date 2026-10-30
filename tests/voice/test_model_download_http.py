"""Owned loopback HTTP only: stopped bodies, cancellation, process death and recovery."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import time
from urllib.request import urlopen

import pytest

from test_model_downloads import setup as setup, start as start, finish as finish

# Shared pytest fixtures are intentionally re-exported for discovery.
__all__ = ['setup']


@pytest.fixture
def slow_server():
    entered, release = Event(), Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "1000000")
            self.end_headers()
            self.wfile.write(b"G")
            self.wfile.flush()
            entered.set()
            release.wait(5)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/body", entered
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_real_stopped_http_body_is_aborted_on_close(setup, slow_server):
    from models.model_downloads import transport

    assert hasattr(transport, "PublicResponse"), "abortable response not implemented"
    m, _, _, _ = setup
    url, entered = slow_server
    # Inject loopback at the transport boundary; production rejects HTTP/local hosts.
    m.transport = lambda _: transport.PublicResponse(urlopen(url, timeout=15))
    start(m)
    assert entered.wait(2)
    time.sleep(0.1)
    begun = time.monotonic()
    assert m.close(timeout=1)
    assert time.monotonic() - begun < 1
    assert finish(m)["phase"] == "cancelled"
    assert not list(m.root.glob(".partial-*")) and not list(m.root.rglob("*.gguf"))


@pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL recovery simulation")
def test_killed_worker_partial_is_reclaimed_under_exclusive_ownership(
    setup, slow_server
):
    m, entry, content, _ = setup
    url, entered = slow_server
    code = """
import io,sys,time,hashlib
from pathlib import Path
from urllib.request import urlopen
from models.model_downloads.catalog import Artifact,Model
from models.model_downloads.manager import Downloads
from models.model_downloads.transport import PublicResponse
content=bytes.fromhex(sys.argv[3])
artifact=Artifact('model.gguf',len(content),hashlib.sha256(content).hexdigest(),'model')
entry=Model('test-model','japanese','Test','Author','author/model','a'*40,'MIT',(),'irodori',(artifact,))
m=Downloads(Path(sys.argv[1]),catalog=(entry,),transport=lambda _:PublicResponse(urlopen(sys.argv[2],timeout=15)),reserve_bytes=0)
m.start({'id':entry.id,'consent':True,'catalog_version':m.catalog_version})
while True: time.sleep(.1)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(m.root), url, content.hex()],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src-python"),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        assert entered.wait(3)
        partials = list(m.root.glob(".partial-*"))
        assert len(partials) == 1
        # A live owner's partial must not be reclaimed by another manager.
        start(m)
        assert finish(m)["error_code"] == "download_busy"
        assert partials[0].is_dir()
        child.kill()
        child.wait(2)
        foreign = m.root / ".partial-user-stuff"
        foreign.mkdir()
        (foreign / "keep").write_text("keep")
        start(m)
        assert finish(m)["phase"] == "ready"
        assert not partials[0].exists()
        assert (foreign / "keep").read_text() == "keep"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(2)
        child.stderr.close()
