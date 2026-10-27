"""Small W3C client for opt-in, actual Tauri acceptance (no IPC mocks).

Contract: https://v2.tauri.app/develop/tests/webdriver/manual-setup/
The caller supplies a built binary and owns its isolated config directory.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]


class NativeWebDriver:
    def __init__(self, output, env=None):
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.session = None
        self.failed = False
        self.extra_env = env or {}

    def request(self, method, path, data=None):
        request = Request(self.base + path, method=method,
                          data=None if data is None else json.dumps(data).encode(),
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)["value"]
        except TimeoutError:
            self.failed = True
            raise

    def command(self, method, path, data=None):
        return self.request(method, f"/session/{self.session}{path}", data)

    def evaluate(self, script, *args):
        return self.command("POST", "/execute/sync", {"script": script, "args": list(args)})

    def wait(self, script, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(script)
            if value:
                return value
            time.sleep(.1)
        body = self.evaluate("return document.body.innerText")
        (self.output / "failure-body.txt").write_text(body)
        raise AssertionError(f"UI condition not met: {script}; see {self.output}")

    def __enter__(self):
        ports = []
        for _ in range(2):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                ports.append(sock.getsockname()[1])
        self.base = f"http://127.0.0.1:{ports[0]}"
        env = dict(os.environ, VRCT_DEV_VENV=".venv_linux",
                   XDG_CACHE_HOME=str(self.output / "cache"),
                   HF_HOME=str(self.output / "hf"), HF_HUB_OFFLINE="1",
                   TRANSFORMERS_OFFLINE="1", **self.extra_env)
        self.log = (self.output / "driver.log").open("w")
        driver = os.environ.get("VRCT_TEST_DRIVER", str(ROOT / "tmp/voice-completion/tauri-driver/bin/tauri-driver"))
        self.process = subprocess.Popen(
            [driver, "--port", str(ports[0]), "--native-port", str(ports[1])],
            env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            for _ in range(100):
                try:
                    self.request("GET", "/status")
                    break
                except OSError:
                    if self.process.poll() is not None:
                        raise RuntimeError("tauri-driver exited before startup")
                    time.sleep(.1)
            binary = os.environ.get("VRCT_TEST_APP", str(ROOT / "src-tauri/build/native-cargo/debug/VRCT"))
            result = self.request("POST", "/session", {"capabilities": {"alwaysMatch": {
                "browserName": "wry", "tauri:options": {"application": binary}}}})
            self.session = result["sessionId"]
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        try:
            if self.session and not self.failed:
                self.command("DELETE", "")
        finally:
            # The owned process group includes WebKit, the app and its sidecar.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
            self.log.close()
