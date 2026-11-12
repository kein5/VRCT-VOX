"""Prepare this PC for the two native tests that put the app's voice into a real VRChat, and put it back.

    python tools/vrchat_voice_host.py prepare      # clients, replay sink, routing; prints the tests' environment
    python tools/vrchat_voice_host.py mic-test     # opens VRChat's microphone test page (see below)
    python tools/vrchat_voice_host.py restore      # undoes all of it

Unlike the other native tests these use the PC's real PipeWire: the managed virtual microphone
(config/pipewire/90-vrct-managed.conf, already installed) is what VRChat records from. What this
changes, and `restore` undoes:

- starts the chatbox lab's two local VRChat clients (hidden local instance) and sizes both to 1600x900;
- loads a null sink "vrct.native.replay" and moves VRChat's playback onto it, so that what VRChat
  plays back can be recorded and nothing else is mixed in;
- mutes the managed route (the tests expect that at the start);
- `mic-test` drives VRChat's own menu with a private ydotoold: Audio & Voice, Volume folded, one
  microphone test run so the page rests in its "new test" state, and noise suppression off for the
  length of the test (it eats parts of synthesized speech). `restore` turns it back on if this
  turned it off.

WirePlumber remembers a moved stream's target per application. `restore` clears that for VRChat, so
VRChat follows the default output again; left alone it would keep playing into the virtual
microphone after a headset is connected.

The menu is driven by position and checked by image after every step, against screenshots taken on
this PC (`calibrate`). A different VRChat layout or language stops with what it saw instead of
clicking on.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src-python"), str(ROOT / "tests/platform")]
CACHE = Path.home() / ".cache/vrct-vox-acceptance/vrchat"
STATE = CACHE / "host-session.json"
SINK, SOURCE, SIZE = "vrct.native.replay", "vrct.managed.source", (1600, 900)
# Fractions of the 1600x900 client area, VRChat 2026.4.1, Japanese UI.
AUDIO_TAB, EXPAND, VOLUME_HEADER = (.534, .861), (.6135, .345), (.372, .207)
TEST_BUTTON, NOISE_TOGGLE, PARK = (.715, .631), (.742, .472), (.40, .26)
NOISE_ROI = "crop=iw*0.05:ih*0.04:iw*0.72:ih*0.452,scale=80:36,format=gray"


def run(*args, check=True, timeout=20, env=None):
    return subprocess.run(list(map(str, args)), capture_output=True, text=True, check=check, timeout=timeout, env=env).stdout.strip()


def vrchat_streams():
    """Node ids of VRChat's playback streams."""
    return [node["id"] for node in json.loads(run("pw-dump", timeout=30))
            if node.get("type", "").endswith("Node")
            and (node.get("info", {}).get("props") or {}).get("application.name") == "VRChat.exe"
            and (node["info"]["props"]).get("media.class") == "Stream/Output/Audio"]


def kwin_windows():
    """role -> (KWin window id, pid) of the lab's clients."""
    import psutil

    import native_vrchat_lab as lab

    ports = {f"--osc={row['osc_in']}:": role for role, row in lab.clients().items()}
    found = {}
    for window in run("kdotool", "search", "--name", "^VRChat$", check=False).split():
        pid = run("kdotool", "getwindowpid", window, check=False)
        if not pid:
            continue
        try:
            command = " ".join(psutil.Process(int(pid)).cmdline())
        except psutil.Error:
            continue
        role = next((role for port, role in ports.items() if port in command), None)
        if role:
            found[role] = (window, pid)
    return found


def mute_route():
    from models.audio_routing.pipewire_gate import PipeWireGate

    gate = PipeWireGate()
    gate.set_muted(True, gate.inspect()["identity"])


def prepare():
    import native_vrchat_lab as lab

    CACHE.mkdir(parents=True, exist_ok=True)
    state = {"started_clients": False, "module": None, "noise_suppression_turned_off": False, "ydotoold": None}
    if not lab.ready():
        run(sys.executable, ROOT / "tools/chatbox_lab/launch_clients.py", "--clients", "2", timeout=300)
        state["started_clients"] = True
        STATE.write_text(json.dumps(state))
        deadline = time.monotonic() + 300
        while not lab.ready():
            if time.monotonic() > deadline:
                raise SystemExit("the VRChat lab clients did not show their windows in time")
            time.sleep(3)
        time.sleep(30)  # both joined, audio streams open
    for window in lab.windows().values():
        run("xdotool", "windowsize", window, *SIZE)
    if SINK not in run("pactl", "list", "short", "sinks"):
        state["module"] = run("pactl", "load-module", "module-null-sink", f"sink_name={SINK}",
                              "sink_properties=device.description=VRCT-acceptance-replay")
    STATE.write_text(json.dumps(state))
    inputs = re.findall(r"Sink Input #(\d+)(?:(?!Sink Input #).)*?application\.name = \"VRChat\.exe\"",
                        run("pactl", "list", "sink-inputs"), re.DOTALL)
    for stream in inputs:
        run("pactl", "move-sink-input", stream, SINK)
    mute_route()
    from tools.vrchat_gui_probe import verify_route

    verify_route(SOURCE, SINK)
    return environment()


def environment():
    """What test_native_chatbox.py and test_native_vrchat.py read."""
    import native_vrchat_lab as lab

    windows = kwin_windows()
    assert set(windows) >= {"speaker", "camera"}, f"lab clients not found: {windows}"
    env = {"VRCT_TEST_VRCHAT_WINDOW": windows["speaker"][0], "VRCT_TEST_VRCHAT_PID": windows["speaker"][1],
           "VRCT_TEST_VRCHAT_VIEW_WINDOW": windows["camera"][0], "VRCT_TEST_VRCHAT_VIEW_PID": windows["camera"][1],
           "VRCT_TEST_REPLAY_SINK": SINK, "VRCT_TEST_VRCHAT_OSC_PORT": str(lab.clients()["speaker"]["osc_in"]),
           "VRCT_TEST_YDOTOOL_SOCKET": socket_path(), "VRCT_TEST_READY_IMAGE": str(CACHE / "ready.png"),
           "VRCT_TEST_RECORDING_IMAGE": str(CACHE / "recording.png")}
    return env


def socket_path():
    # Under 108 bytes, or the client fails without saying so.
    return os.environ["XDG_RUNTIME_DIR"] + "/vrct-acc-ydotool.sock"


def daemon_running():
    import psutil

    for process in psutil.process_iter(["cmdline"]):
        command = process.info["cmdline"] or []
        if command[:1] == ["ydotoold"] and f"--socket-path={socket_path()}" in command:
            return True
    return False


class Menu:
    """VRChat's menu in the speaker's window, driven with a private ydotoold and checked by image."""

    def __init__(self):
        self.window, self.pid = kwin_windows()["speaker"]
        self.env = {**os.environ, "YDOTOOL_SOCKET": socket_path()}
        state = json.loads(STATE.read_text())
        if not daemon_running():
            Path(socket_path()).unlink(missing_ok=True)  # a daemon that was killed leaves its socket behind
            daemon = subprocess.Popen(["ydotoold", f"--socket-path={socket_path()}"], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True)
            state["ydotoold"] = daemon.pid
            STATE.write_text(json.dumps(state))
            # The client fails with status 2 until the daemon has made its socket and its device.
            deadline = time.monotonic() + 10
            while not Path(socket_path()).exists():
                assert daemon.poll() is None and time.monotonic() < deadline, "ydotoold did not start (is this user in the uinput group?)"
                time.sleep(.1)
            time.sleep(1)

    def focus(self):
        assert run("kdotool", "getwindowpid", self.window) == self.pid
        run("kdotool", "windowactivate", self.window)
        time.sleep(.4)
        assert run("kdotool", "getactivewindow") == self.window, "VRChat's window did not take focus"

    def origin(self):
        geometry = run("kdotool", "getwindowgeometry", self.window)
        x, y = map(int, re.search(r"Position: (-?\d+),(-?\d+)", geometry).groups())
        width, height = map(int, re.search(r"Geometry: (\d+)x(\d+)", geometry).groups())
        assert width == SIZE[0] and 0 <= height - SIZE[1] <= 60, geometry
        return x, y + height - SIZE[1]

    def move(self, position):
        self.focus()
        x, y = self.origin()
        target = x + round(position[0] * SIZE[0]), y + round(position[1] * SIZE[1])
        for _ in range(40):
            location = run("kdotool", "getmouselocation", "--shell")
            now = tuple(map(int, re.search(r"X=(-?\d+)\nY=(-?\d+)", location).groups()))
            dx, dy = target[0] - now[0], target[1] - now[1]
            if max(abs(dx), abs(dy)) <= 2:
                return
            step = [(round(d / 2) or (1 if d > 0 else -1)) if d else 0 for d in (dx, dy)]
            run("ydotool", "mousemove", "-x", step[0], "-y", step[1], env=self.env)
            time.sleep(.06)
        raise SystemExit("the pointer did not reach its target")

    def click(self, position):
        self.move(position)
        time.sleep(.15)
        run("ydotool", "click", "0xC0", env=self.env)
        time.sleep(1.2)

    def escape(self):
        self.focus()
        run("ydotool", "key", "1:1", "1:0", env=self.env)
        time.sleep(1.5)

    def shot(self, name):
        self.move(PARK)  # keeps the pointer and its hover tint off the parts that are compared
        path = CACHE / f"{name}.png"
        run("spectacle", "-a", "-b", "-n", "-e", "-S", "-o", path)
        return path


def score(path, template, roi=None):
    from tools.vrchat_gui_probe import image_score, pixels

    if roi is None:
        return image_score(pixels(path), pixels(template))
    crop = lambda file: subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(file), "-vf", roi, "-f", "rawvideo", "-"], timeout=10)  # noqa: E731
    return image_score(crop(path), crop(template))


def page_state(menu):
    """'start', 'ready' (a test has run) or None, from the test button's place on the page."""
    shot = menu.shot("now")
    scores = {name: score(shot, CACHE / f"{name}.png") for name in ("start", "ready") if (CACHE / f"{name}.png").is_file()}
    best = max(scores, key=scores.get, default=None)
    return best if best and scores[best] >= .8 else None


def open_mic_test(calibrate=False):
    """Leave the speaker's VRChat on Audio & Voice with a finished microphone test and noise suppression off."""
    menu = Menu()
    state = json.loads(STATE.read_text())
    if calibrate or page_state(menu) is None:
        menu.escape()  # quick menu
        for _ in range(2):
            # A news card can lie over the quick menu. Its close button is where EXPAND is,
            # so the first pass closes the card and the second opens the page.
            menu.click(AUDIO_TAB)
            menu.click(EXPAND)  # the full Audio & Voice page
            if calibrate or page_state(menu) is None:
                menu.click(VOLUME_HEADER)  # VRChat remembers a folded Volume; fold it only when it is open
            if calibrate or page_state(menu) is not None:
                break
    if calibrate:
        menu.shot("start")
        menu.click(TEST_BUTTON)
        menu.shot("recording")
        time.sleep(24)           # ten seconds of recording, ten of playback
        menu.shot("ready")
        menu.shot("noise-on")    # taken with noise suppression on; turn it on by hand before calibrating
        print(f"calibrated: {sorted(p.name for p in CACHE.glob('*.png'))}")
    where = page_state(menu)
    if where is None:
        raise SystemExit(f"VRChat is not on the microphone test page as calibrated; see {CACHE / 'now.png'}")
    if where == "start":
        menu.click(TEST_BUTTON)
        time.sleep(24)
        if page_state(menu) != "ready":
            raise SystemExit(f"the microphone test did not finish as calibrated; see {CACHE / 'now.png'}")
    if score(menu.shot("now"), CACHE / "noise-on.png", NOISE_ROI) >= .8:
        menu.click(NOISE_TOGGLE)
        state["noise_suppression_turned_off"] = True
        STATE.write_text(json.dumps(state))
        assert score(menu.shot("now"), CACHE / "noise-on.png", NOISE_ROI) < .8, "noise suppression did not turn off"
    assert page_state(menu) == "ready"


def restore():
    import native_vrchat_lab as lab

    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    if state.get("noise_suppression_turned_off") and "speaker" in kwin_windows():
        menu = Menu()
        if score(menu.shot("now"), CACHE / "noise-on.png", NOISE_ROI) < .8:
            menu.click(NOISE_TOGGLE)
        if score(menu.shot("now"), CACHE / "noise-on.png", NOISE_ROI) < .8:
            print("WARNING: could not confirm that VRChat's noise suppression is back on", file=sys.stderr)
        menu.escape()
    for stream in vrchat_streams():  # forget the moved target: VRChat follows the default output again
        run("pw-metadata", "-n", "default", "--", stream, "target.object", "-1", "Spa:Id", check=False)
        run("pw-metadata", "-n", "default", "--", stream, "target.node", "-1", "Spa:Id", check=False)
    time.sleep(2)
    if state.get("started_clients") and lab.clients():
        run(sys.executable, ROOT / "tools/chatbox_lab/launch_clients.py", "--stop", check=False, timeout=120)
        time.sleep(4)
    if state.get("module"):
        run("pactl", "unload-module", state["module"], check=False)
    if state.get("ydotoold"):
        subprocess.run(["kill", str(state["ydotoold"])], capture_output=True)
        Path(socket_path()).unlink(missing_ok=True)
    try:
        mute_route()
    except Exception as error:  # the route may be gone with the app; say so rather than fail the restore
        print(f"WARNING: could not mute the managed route: {type(error).__name__}", file=sys.stderr)
    stored = Path.home() / ".local/state/wireplumber/stream-properties"
    if stored.is_file() and any("VRChat.exe" in line and SINK in line for line in stored.read_text(errors="replace").splitlines()):
        print(f"WARNING: WirePlumber still remembers {SINK} for VRChat", file=sys.stderr)
    STATE.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["prepare", "env", "mic-test", "calibrate", "restore"])
    args = parser.parse_args(argv)
    if args.action in ("prepare", "env"):
        env = prepare() if args.action == "prepare" else environment()
        print("\n".join(f"{key}={value}" for key, value in env.items()))
    elif args.action in ("mic-test", "calibrate"):
        open_mic_test(calibrate=args.action == "calibrate")
    else:
        restore()


if __name__ == "__main__":
    main()
