"""Run the built app against the fake SteamVR and drive it with the fake controller.

The VR page is looked at through what the app hands to (fake) SteamVR: `state.json` and one PNG
per overlay, written once a second by tools/fake_vr_site. The controller is moved by rewriting
`control.json`. WebDriver is not used: on Linux the VR page restarts its web process when it moves
off the desktop (src-tauri/src/vr_panel_surface.rs), which WebKit's driver reports as a page crash.
"""
import hashlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Region sizes in page pixels (src-ui/views/vr/vr_layout.json) and the overlay that shows each.
LAUNCHER = ("VRCT3", (880, 128))
LOG = ("VRCT2", (900, 700))
POPUP = ("VRCT4", (720, 640))
TOOLBAR = ("VRCT_toolbar", (720, 96))


class FakeVrApp:
    def __init__(self, output, config=None):
        self.output = Path(output).resolve()
        self.fake = self.output / "fake-vr"
        state = self.output / "config/vrct-vox"
        state.mkdir(parents=True, exist_ok=True)
        (state / "config.json").write_text(json.dumps({
            "AUTO_DOWNLOAD_MODELS": False, "ENABLE_TELEMETRY": False, "TELEMETRY_NOTICE": 1, "AUTO_MIC_SELECT": False,
            "AUTO_SPEAKER_SELECT": False, "SEND_MESSAGE_TO_VRC": False, "VRC_MIC_MUTE_SYNC": False,
            "OSC_IP_ADDRESS": "127.0.0.2", "WEBSOCKET_SERVER": False, "UI_LANGUAGE": "en",
            # Shown at startup, and not only while the (fake) head looks at the wrist.
            "OVERLAY_VR_PANEL": True, "OVERLAY_VR_LAUNCHER_AUTO_HIDE": False, **(config or {}),
        }))
        self.log = state / "logs/process.log"
        self.serial = 0
        self.process = None

    def __enter__(self):
        binary = os.environ.get("VRCT_TEST_APP", str(ROOT / "src-tauri/build/native-cargo/debug/vrct-vox"))
        env = dict(os.environ, VRCT_DEV_VENV=".venv_linux",
                   XDG_CONFIG_HOME=str(self.output / "config"), XDG_DATA_HOME=str(self.output / "data"),
                   XDG_CACHE_HOME=str(self.output / "cache"), VRCT_CONFIG_DIR=str(self.output / "config/vrct-vox"),
                   HF_HOME=str(self.output / "hf"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", VRCT_TELEMETRY="off",
                   PYTHONPATH=str(ROOT / "tools/fake_vr_site"), VOX_FAKE_VR_OUT=str(self.fake))
        self.stdout = (self.output / "app.log").open("w")
        self.process = subprocess.Popen([binary], env=env, stdout=self.stdout, stderr=subprocess.STDOUT,
                                        start_new_session=True, cwd=ROOT)
        return self

    def __exit__(self, *args):
        # The sidecar and its children share the app's process group.
        for wait, sign in ((8, signal.SIGTERM), (3, signal.SIGKILL)):
            try:
                os.killpg(self.process.pid, sign)
            except ProcessLookupError:
                break
            try:
                self.process.wait(wait)
            except subprocess.TimeoutExpired:
                continue
            time.sleep(.5)
        self.stdout.close()

    def state(self):
        try:
            return json.loads((self.fake / "state.json").read_text())
        except (OSError, ValueError):
            return None

    def overlay(self, key):
        return next((row for row in (self.state() or {}).get("overlays", []) if row["key"] == key), None)

    def wait(self, condition, timeout=30, what=""):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            assert self.process.poll() is None, f"the app exited with {self.process.returncode} while waiting for {what}"
            value = condition()
            if value:
                return value
            time.sleep(.25)
        raise AssertionError(f"timed out: {what}")

    def control(self, **values):
        """One change of the fake controller. The recorder looks once a second and applies it once."""
        self.serial += 1
        path = self.fake / "control.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(dict(values, serial=self.serial)))
        os.replace(temporary, path)
        time.sleep(1.3)

    def aim(self, target, at):
        """Point the right hand's laser at page pixel `at` of the region that `target` shows."""
        key, (width_px, height_px) = target
        width_m = self.overlay(key)["width_m"]
        x = (at[0] / width_px - .5) * width_m
        y = (.5 - at[1] / height_px) * width_m * height_px / width_px
        self.control(aim={"device": "right", "overlay": key, "at": [x, y], "distance": 0.4})

    def click(self):
        self.control(press={"right": ["trigger"]})
        self.control(release={"right": ["trigger"]})

    def stick(self, x, y):
        self.control(stick={"right": [x, y]})

    def image(self, target):
        """A digest of what the overlay shows now."""
        return hashlib.sha256((self.fake / f"{target[0]}.png").read_bytes()).hexdigest()

    def log_lines(self, needle):
        try:
            return [line for line in self.log.read_text().splitlines() if needle in line]
        except OSError:
            return []
