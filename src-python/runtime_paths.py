"""Fixed resources and per-user state for the Linux frozen distribution."""
import os
from pathlib import Path
import sys


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def linux_directories(env=None, home=None):
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    result = {}
    for kind, xdg, fallback in [("config", "XDG_CONFIG_HOME", ".config"),
                                ("data", "XDG_DATA_HOME", ".local/share"),
                                ("cache", "XDG_CACHE_HOME", ".cache")]:
        override = env.get(f"VRCT_{kind.upper()}_DIR")
        if override:
            result[kind] = Path(override).expanduser().resolve()
        else:
            base = Path(env.get(xdg) or "")
            result[kind] = (base if base.is_absolute() else home / fallback) / "vrct-tts"
    return result


def is_linux_frozen():
    return sys.platform == "linux" and bool(getattr(sys, "frozen", False))


def data_root(legacy):
    return linux_directories()["data"] if is_linux_frozen() else Path(legacy)


def bootstrap_linux_frozen():
    if not is_linux_frozen():
        return
    dirs = linux_directories()
    for kind, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.environ[f"VRCT_{kind.upper()}_DIR"] = str(path)
    (dirs["config"] / "logs").mkdir(exist_ok=True, mode=0o700)
    os.environ.setdefault("HF_HOME", str(dirs["cache"] / "huggingface"))
    # Remaining legacy relative files (e.g. user logs) must not write beside
    # the installed executable or into whichever directory launched the GUI.
    os.chdir(dirs["data"])


def external_process_env():
    env = dict(os.environ)
    if is_linux_frozen():
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original:
            env["LD_LIBRARY_PATH"] = original
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env
