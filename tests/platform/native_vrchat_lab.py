"""The two local VRChat clients of the chatbox lab, as the round-trip test needs them.

tools/chatbox_lab/launch_clients.py starts a speaker and a camera in a hidden local instance and
records them in clients.json. Both windows are titled "VRChat"; the app's chat reading looks for
that title, and the speaker never shows its own bubble. This module tells the two windows apart by
the OSC port of the process that owns each, and gives the speaker's window another title for the
length of a test.
"""
import json
import os
import subprocess
from pathlib import Path

CLIENTS = Path(os.environ.get("VRCT_TEST_VRCHAT_CLIENTS", Path.home() / ".cache/vrct-vox-chatbox-lab/clients.json"))
TITLE = "VRChat"
SPEAKER_TITLE = "Chatbox lab speaker"


def clients():
    """role -> record of clients.json, or {} when the lab is not running."""
    try:
        rows = json.loads(CLIENTS.read_text())["clients"]
    except (OSError, ValueError, KeyError):
        return {}
    return {row["role"]: row for row in rows}


def _xdotool(*args):
    return subprocess.run(["xdotool", *map(str, args)], capture_output=True, text=True, timeout=10).stdout.split()


def windows():
    """role -> X11 window id. Each window's process carries its client's OSC port on its command line
    (Wine reparents it, so it is not a descendant of the launcher)."""
    import psutil

    ports = {f"--osc={row['osc_in']}:": role for role, row in clients().items()}
    found = {}
    for title in (TITLE, SPEAKER_TITLE):
        for window in _xdotool("search", "--name", f"^{title}$"):
            owner = _xdotool("getwindowpid", window)
            if not owner:
                continue
            try:
                command = " ".join(psutil.Process(int(owner[0])).cmdline())
            except psutil.Error:
                continue
            role = next((role for port, role in ports.items() if port in command), None)
            if role:
                found[role] = window
    return found


def ready():
    return set(windows()) >= {"speaker", "camera"}


class OnlyCameraNamedVRChat:
    """While inside, the camera's window is the only one titled "VRChat"."""

    def __enter__(self):
        self.found = windows()
        assert set(self.found) >= {"speaker", "camera"}, f"lab clients not found: {self.found}"
        _xdotool("set_window", "--name", SPEAKER_TITLE, self.found["speaker"])
        _xdotool("set_window", "--name", TITLE, self.found["camera"])
        return self.found

    def __exit__(self, *args):
        _xdotool("set_window", "--name", TITLE, self.found["speaker"])
