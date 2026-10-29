"""Small W3C client for opt-in, actual Tauri acceptance (no IPC mocks).

Contract: https://v2.tauri.app/develop/tests/webdriver/manual-setup/
The caller supplies a built binary and owns its isolated config directory.
"""
import base64
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.display_power_guard import check_displays_on  # noqa: E402


class NativeWebDriver:
    def __init__(self, output, env=None):
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.session = None
        self.failed = False
        self.extra_env = env or {}

    def request(self, method, path, data=None):
        # urllib forces Connection: close. tauri-driver 2.1.0 forwards that
        # hop-local header into its pooled native-driver connection; this host
        # intermittently reset it during ordinary commands. Avoid that header
        # rather than retrying a command which might already have taken effect.
        conn = http.client.HTTPConnection(self.base.removeprefix("http://"), timeout=15)
        try:
            conn.request(method, path, body=None if data is None else json.dumps(data).encode(),
                         headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            raw = response.read()
            if response.status >= 400:
                raise AssertionError(f"WebDriver {method} {path}: {raw.decode(errors='replace')}")
            return json.loads(raw)["value"]
        except (TimeoutError, http.client.HTTPException):
            self.failed = True
            raise
        finally:
            conn.close()

    def command(self, method, path, data=None):
        return self.request(method, f"/session/{self.session}{path}", data)

    def evaluate(self, script, *args):
        return self.command("POST", "/execute/sync", {"script": script, "args": list(args)})

    def element_command(self, element, action, data=None):
        key = "element-6066-11e4-a52e-4f735466cecf"
        assert element and key in element, f"missing UI element for {action}"
        self.evaluate("const e = arguments[0].tagName === 'OPTION' ? arguments[0].parentElement : arguments[0]; e.scrollIntoView({block:'center', inline:'center', behavior:'instant'}); return true;", element)
        deadline = time.monotonic() + 5
        while True:
            try:
                return self.command("POST", f"/element/{element[key]}/{action}", data or {})
            except AssertionError as error:
                if action not in ("click", "clear", "value") or not any(code in str(error) for code in ('"element click intercepted"', '"element not interactable"')) or time.monotonic() >= deadline:
                    raise
                notice = self.evaluate("return [...document.querySelectorAll('.Toastify__toast')].find(e => e.textContent.startsWith('Built-in translation or transcription models are unavailable.') || e.textContent.startsWith('Network is not connected.'))?.querySelector('button svg');")
                if notice:
                    try:
                        self.command("POST", f"/element/{notice[key]}/click", {})
                    except AssertionError as notice_error:
                        if not any(code in str(notice_error) for code in ('"element not interactable"', '"element click intercepted"', '"stale element reference"')):
                            raise
                # The configuration drawer animates. Retry only interactions
                # WebDriver explicitly says were not delivered.
                time.sleep(.1)

    def click(self, selector):
        element = self.command("POST", "/element", {"using": "css selector", "value": selector})
        return self.element_command(element, "click")

    def click_text(self, tag, text):
        # Main and the hidden configuration page can expose the same label.
        # Select the visible control, retaining native WebDriver hit testing.
        element = self.evaluate("return [...document.querySelectorAll(arguments[0])].find(e => e.textContent.trim() === arguments[1] && getComputedStyle(e).visibility === 'visible' && e.getClientRects().length);", tag, text)
        return self.element_command(element, "click")

    def control(self, label):
        return self.evaluate("return [...document.querySelectorAll('label')].find(e => e.firstChild.textContent.trim() === arguments[0])?.querySelector('input,select');", label)

    def fill(self, label, value):
        control = self.control(label)
        self.element_command(control, "clear")
        self.element_command(control, "value", {"text": value})

    def select(self, label, value):
        option = self.evaluate("return [...arguments[0].options].find(e => e.value === arguments[1]);", self.control(label), value)
        self.element_command(option, "click")

    def open_voice_settings(self):
        # The text input can mount while the native window is still the 450x220
        # splash. These isolated tests expect the normal main-window geometry
        # (also asserted by assert_rendered); wait for it and actual frames before
        # the first coordinate-based navigation. Do not retry successful clicks.
        self.wait("return innerWidth >= 500 && innerHeight >= 300")
        self.assert_rendered()
        self.open_settings()
        if not self.evaluate("return document.querySelector('section[aria-label=\"Text to voice (speech.cpp)\"] select') !== null"):
            # Compact sidebars hide the label until hovered; the tab's icon and
            # hit area remain visible and are the real navigation control.
            tab = self.evaluate("return [...document.querySelectorAll('p')].find(e => e.textContent === 'Advanced')?.parentElement;")
            self.element_command(tab, "click")
        self.wait("return document.querySelector('section[aria-label=\"Text to voice (speech.cpp)\"] select') !== null")

    def close_app(self):
        """Use the app's real shutdown action and verify exit before driver cleanup."""
        self.click('[class*="window_control_wrapper"] [class*="close_button"]')
        self.app_process.wait(timeout=10)
        # The app has closed its own automation target; don't ask WebKit to close
        # it a second time. The owned driver group is still reaped by __exit__.
        self.session = None

    def close_settings(self):
        # The label moves on hover. Its parent bar is the actual click handler
        # and its central hit point stays inside the bar while it expands.
        self.click('[class*="show_config"] > [class*="_wrapper_"]')
        self.wait("return document.querySelector('[class*=show_main]') !== null && [...document.querySelectorAll('[class*=go_back_text]')].every(e => getComputedStyle(e).visibility === 'hidden')")

    def open_settings(self):
        self.click('[class*="open_config_page_button"]')
        # Visibility can remain true for 0.5s while the old page is closing.
        # Observe the explicit open state and the end of its moving top bar.
        self.wait("const bar = document.querySelector('[class*=show_config] > [class*=\"_wrapper_\"]')?.parentElement; return !!bar && getComputedStyle(bar).top === '0px';")

    def assert_rendered(self):
        """Observe real frame delivery and a nonblank native WebDriver image."""
        from PIL import Image, ImageStat

        before = check_displays_on()
        self.evaluate("window.__vrctFrames = 0; function tick() { if (++window.__vrctFrames < 3) requestAnimationFrame(tick); } requestAnimationFrame(tick); return true;")
        try:
            self.wait("return window.__vrctFrames >= 3", timeout=5)
            screenshot = self.command("GET", "/screenshot")
        finally:
            # Report power loss separately from an application rendering failure.
            after = check_displays_on()
        path = self.output / "rendered.png"
        path.write_bytes(base64.b64decode(screenshot, validate=True))
        with Image.open(path) as shot:
            rgba = shot.convert("RGBA")
            alpha = rgba.getchannel("A").getextrema()
            variance = ImageStat.Stat(rgba.convert("RGB")).var
            report = {"size": list(shot.size), "alpha": alpha, "variance": variance,
                      "displays_before": before, "displays_after": after}
            (self.output / "rendered.json").write_text(json.dumps(report, indent=2))
            assert shot.width >= 500 and shot.height >= 300, report
            assert alpha[1] == 255 and max(variance) > 1, report
        return report

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
        check_displays_on()
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
            binary = os.environ.get("VRCT_TEST_APP", str(ROOT / "src-tauri/build/native-cargo/debug/vrct-tts"))
            result = self.request("POST", "/session", {"capabilities": {"alwaysMatch": {
                "browserName": "wry", "tauri:options": {"application": binary}}}})
            self.session = result["sessionId"]
            import psutil
            apps = [child for child in psutil.Process(self.process.pid).children(recursive=True)
                    if child.exe() == str(Path(binary).resolve())]
            assert len(apps) == 1, "could not identify the owned Tauri process"
            self.app_process = apps[0]
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def terminate_owned_processes(self):
        """Bound teardown by the owned tree, including children outliving driver."""
        import psutil

        try:
            leader = psutil.Process(self.process.pid)
            owned = [*leader.children(recursive=True), leader]
        except psutil.NoSuchProcess:
            owned = []

        def signal_group(value):
            try:
                os.killpg(self.process.pid, value)
            except ProcessLookupError:
                pass

        def living():
            # poll reaps our Popen child. Reparented zombies cannot execute or
            # hold audio endpoints and are reaped by their new parent.
            self.process.poll()
            active = []
            for process in owned:
                try:
                    if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                        active.append(process)
                except psutil.NoSuchProcess:
                    pass
            return active

        signal_group(signal.SIGTERM)
        for process in owned:
            try:
                process.terminate()  # Also reaches descendants in another group.
            except psutil.NoSuchProcess:
                pass
        deadline = time.monotonic() + 5
        while living() and time.monotonic() < deadline:
            time.sleep(.05)
        # The leader may already be gone; that is not evidence its children are.
        signal_group(signal.SIGKILL)
        for process in living():
            try:
                process.kill()  # psutil checks PID reuse before signalling.
            except psutil.NoSuchProcess:
                pass
        self.process.wait(timeout=3)
        deadline = time.monotonic() + 3
        while living() and time.monotonic() < deadline:
            time.sleep(.05)
        assert not living(), "owned native process survived teardown"

    def __exit__(self, *args):
        try:
            if args and args[0] is not None and self.session and not self.failed:
                try:
                    (self.output / "failure-body.txt").write_text(self.evaluate("return document.body.innerText"))
                    self.assert_rendered()
                except Exception as error:
                    (self.output / "failure-capture-error.txt").write_text(repr(error))
            if self.session and not self.failed:
                try:
                    self.command("DELETE", "")
                except Exception as error:
                    (self.output / "cleanup-error.txt").write_text(repr(error))
                    if not args or args[0] is None:
                        raise
        finally:
            try:
                self.terminate_owned_processes()
            finally:
                self.log.close()
