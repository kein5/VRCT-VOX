"""Drives the real backend over stdio. VRChat is a local OSC listener, SteamVR the fake runtime."""
import base64
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from queue import Empty, Queue

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

ROOT = Path(os.environ.get('VOX_FIELD_ROOT') or Path(__file__).resolve().parents[2])
SCRATCH = Path(__file__).resolve().parent


class Backend:
    def __init__(self, out, *, audio=False):
        self.out = Path(out)
        self.state, self.fake = self.out / "state", self.out / "fake-vr"
        self.audio_dir = self.out / "audio"
        for path in (self.state, self.fake, self.audio_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.results = []
        self.osc = Queue()
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(lambda address, *args: self.osc.put((address, args)))
        try:
            if os.environ.get("VOX_NO_OSC_LISTENER"):  # the real VRChat owns the port
                raise OSError("left to VRChat")
            self.server = ThreadingOSCUDPServer(("127.0.0.1", 9000), dispatcher)
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
        except OSError:
            self.server = None  # Another test owns the port; OSC is not checked then.
        env = dict(os.environ, VRCT_CONFIG_DIR=str(self.state), PYTHONPATH=str(SCRATCH / "site"),
                   VOX_REPO=str(ROOT), VOX_FAKE_VR_OUT=str(self.fake), PYTHONIOENCODING="utf-8")
        env.pop("HF_HUB_OFFLINE", None)
        if audio:
            env["VOX_FAKE_AUDIO_DIR"] = str(self.audio_dir)
        self.ocr_frame = self.audio_dir / "ocr-frame.png"
        env["VOX_FAKE_OCR_FRAME"] = str(self.ocr_frame)
        env["VOX_FAKE_DETECTOR_CONFIDENCE"] = "0.05"
        self.stderr = (self.out / "stderr.log").open("a", encoding="utf-8")
        self.process = subprocess.Popen(
            [os.environ.get("VOX_APP_PYTHON") or str(ROOT / ".venv/Scripts/python.exe"), "-u", str(ROOT / "src-python/mainloop.py")],
            cwd=ROOT / "src-python", env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.stderr, text=True, encoding="utf-8")
        self.events = Queue()
        self.seen = []
        self.last_feed = 0.0
        threading.Thread(target=self._collect, daemon=True).start()

    def _collect(self):
        with (self.out / "stdout.log").open("a", encoding="utf-8") as log:
            for line in self.process.stdout:
                log.write(line)
                log.flush()
                try:
                    self.events.put(json.loads(line))
                except ValueError:
                    pass

    def record(self, step, ok, detail=""):
        self.results.append({"step": step, "ok": bool(ok), "detail": str(detail)})
        print(f"[{'PASS' if ok else 'FAIL'}] {step}: {detail}", flush=True)

    def send(self, endpoint, data=None):
        payload = None if data is None else base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
        self.process.stdin.write(json.dumps({"endpoint": endpoint, "data": payload}) + "\n")
        self.process.stdin.flush()

    def pump(self, seconds=0.2):
        """Keep the watchdog fed and collect one event, or None."""
        if self.process.poll() is not None:
            raise RuntimeError(f"backend exited with {self.process.returncode}")
        if time.monotonic() - self.last_feed > 10:
            self.send("/run/feed_watchdog")
            self.last_feed = time.monotonic()
        try:
            event = self.events.get(timeout=seconds)
        except Empty:
            return None
        if event.get("status") != 348:
            self.seen.append(event)
        return event

    def wait(self, endpoint, timeout=40.0, predicate=lambda event: True):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.pump()
            if event and event.get("endpoint") == endpoint and event.get("status") != 348 and predicate(event):
                return event
        raise TimeoutError(endpoint)

    def call(self, endpoint, data=None, timeout=40.0):
        self.send(endpoint, data)
        return self.wait(endpoint, timeout)

    def start(self):
        started = time.monotonic()
        event = self.wait("/run/initialization_complete", timeout=180)
        self.init = event.get("result") or {}
        self.record("startup", event["status"] == 200, f"{time.monotonic() - started:.1f}s")
        return self.init

    def osc_wait(self, address, timeout=5.0, predicate=lambda args: True):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump(0.02)
            try:
                got, args = self.osc.get(timeout=0.05)
            except Empty:
                continue
            if got == address and predicate(args):
                return args
        return None

    def drain_osc(self):
        while not self.osc.empty():
            self.osc.get()

    def fake_state(self):
        try:
            return json.loads((self.fake / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.stdin.close()
                self.process.wait(timeout=40)
        except Exception as error:  # noqa: BLE001
            print("close:", repr(error), flush=True)
        finally:
            if self.process.poll() is None:
                self.process.kill()
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()
        with (self.out / "results.jsonl").open("a", encoding="utf-8") as stream:
            for row in self.results:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{sum(r['ok'] for r in self.results)}/{len(self.results)} passed", flush=True)
