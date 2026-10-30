#!/usr/bin/env python3
"""Keep the displays awake and verify they are on while a native GUI test runs (Linux, KDE Wayland).

Why this exists (2026-10-28 investigation, docs/linux_native_ui_black_screen_2026-10-28.md):
On Wayland the compositor stops presenting outputs that are powered off (DPMS "Off").
Surfaces on those outputs get no frame callbacks, so GTK / WebKitGTK stop painting,
requestAnimationFrame never fires, pending window resizes are never committed and a
window capture is fully transparent (shown as black). An unattended acceptance run that
starts after KDE's idle timeout therefore looks like a "black screen / rendering stopped"
application bug. The reproduction recovered as soon as the output was on; the historical
2026-10-27 power state was not recorded.

Usage:
  uv run --no-project --python /usr/bin/python3 python tools/display_power_guard.py --check
  uv run --no-project --python /usr/bin/python3 python tools/display_power_guard.py --hold 180
  uv run --no-project --python /usr/bin/python3 python tools/display_power_guard.py -- <command...>

The guard requires PyGObject (Gio), normally available in the desktop's system Python.
The guarded command can use a separate uv environment. A systemd idle lock alone has
not been verified to inhibit KDE display power management, so there is no silent fallback.
Power is sampled during the command and at exit; a failed precondition returns code 2.
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

DRM = Path("/sys/class/drm")


def connected_outputs():
    """{connector name: "On" | "Off" | ...} for every connected DRM connector."""
    state = {}
    for connector in sorted(DRM.glob("card*-*")):
        status, dpms = connector / "status", connector / "dpms"
        if status.is_file() and status.read_text().strip() == "connected":
            state[connector.name] = dpms.read_text().strip() if dpms.is_file() else "Unknown"
    return state


def displays_on(state=None):
    state = connected_outputs() if state is None else state
    return bool(state) and all(value == "On" for value in state.values())


class Inhibitor:
    """Holds a screen-saver / idle inhibition for as long as the object is alive."""

    def __init__(self, who="vrct-native-ui-test", why="native GUI acceptance test"):
        self.who, self.why, self.kind = who, why, None
        self._proxy = self._cookie = None

    def __enter__(self):
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as error:
            raise RuntimeError("display inhibition requires PyGObject (Gio); run the guard with /usr/bin/python3 via uv") from error
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as error:
            raise RuntimeError(f"display inhibition cannot connect to the session bus: {error}") from error
        targets = (
            ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver"),
            ("org.freedesktop.PowerManagement", "/org/freedesktop/PowerManagement/Inhibit", "org.freedesktop.PowerManagement.Inhibit"),
        )
        errors = []
        for name, path, interface in targets:
            try:
                proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.NONE, None, name, path, interface, None)
                reply = proxy.call_sync("Inhibit", GLib.Variant("(ss)", (self.who, self.why)), Gio.DBusCallFlags.NONE, 5000, None)
                self._bus, self._proxy, self._cookie, self.kind = bus, proxy, reply.unpack()[0], f"dbus:{interface}"
                return self
            except Exception as error:
                errors.append(f"{interface}: {error}")
        raise RuntimeError("display inhibition unavailable: " + "; ".join(errors))

    def __exit__(self, *exc):
        if self._proxy is not None:
            try:
                from gi.repository import Gio, GLib
                self._proxy.call_sync("UnInhibit", GLib.Variant("(u)", (self._cookie,)), Gio.DBusCallFlags.NONE, 5000, None)
            except Exception:
                pass


def check_displays_on():
    """Assert the rendering precondition without hiding a power loss by waking it."""
    state = connected_outputs()
    if not displays_on(state):
        raise RuntimeError(f"display outputs are not on: {state}; run GUI tests under tools/display_power_guard.py")
    return state


def wake():
    """Turn the outputs on and reset the desktop idle timer (best effort, KDE Plasma)."""
    if shutil.which("kscreen-doctor"):
        subprocess.run(["kscreen-doctor", "--dpms", "on"], capture_output=True, text=True, timeout=15)
    if shutil.which("gdbus"):
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.ScreenSaver",
                        "--object-path", "/org/freedesktop/ScreenSaver",
                        "--method", "org.freedesktop.ScreenSaver.SimulateUserActivity"],
                       capture_output=True, text=True, timeout=10)


def require_displays_on(timeout=20.0):
    """Wake the displays and wait until every connected output reports DPMS On."""
    deadline = time.monotonic() + timeout
    while True:
        state = connected_outputs()
        if displays_on(state):
            return state
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"display outputs are not on: {state}. A Wayland compositor does not present powered-off outputs, "
                "so the application cannot paint; wake the display (kscreen-doctor --dpms on) before judging rendering.")
        wake()
        time.sleep(2)


def run_guarded(args):
    with Inhibitor() as inhibitor:
        print(f"inhibitor: {inhibitor.kind}", flush=True)
        print(f"displays on: {require_displays_on()}", flush=True)
        if args.hold is not None:
            deadline = time.monotonic() + args.hold
            while True:
                print(check_displays_on(), flush=True)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 0
                time.sleep(min(args.poll, remaining))
        valid = True
        # Do not interrupt a GUI test on a power change: let its own bounded
        # requests and teardown finish, but invalidate the entire result.
        with subprocess.Popen(args.command) as process:
            try:
                while True:
                    state = connected_outputs()
                    if not displays_on(state):
                        if valid:
                            print(f"display precondition lost during the run: {state}", file=sys.stderr)
                        valid = False
                    try:
                        code = process.wait(timeout=args.poll)
                        check_displays_on()
                        return code if valid else 2
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="print the output power state and exit")
    parser.add_argument("--hold", type=float, help="self-test: keep the inhibition for this many seconds")
    parser.add_argument("--poll", type=float, default=1.0, help="seconds between power checks (default: 1)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command to run under the guard (after --)")
    args = parser.parse_args()

    if args.check:
        state = connected_outputs()
        print(state)
        return 0 if displays_on(state) else 1

    args.command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if args.poll <= 0 or (args.hold is not None and args.hold < 0):
        parser.error("--poll must be positive and --hold nonnegative")
    if not args.command and args.hold is None:
        parser.error("no command given; use --check, --hold N, or -- <command...>")
    if args.command and args.hold is not None:
        parser.error("use --hold or a command, not both")
    try:
        return run_guarded(args)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
