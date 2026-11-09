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
            # Stable storage identity: VRCT-VOX reuses existing settings and models.
            result[kind] = (base if base.is_absolute() else home / fallback) / "vrct-vox"
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


_backend_only_env = set()
_OPENMP_WAIT_SETTINGS = {"KMP_BLOCKTIME": "0", "KMP_USE_YIELD": "0"}


def limit_openmp_spinning():
    """Make CTranslate2's OpenMP threads sleep instead of spinning or yielding.

    With more runnable threads than cores (VRChat, a game) one Whisper call went
    from 1 s to minutes. Intel OpenMP spins for 200 ms between parallel regions,
    which takes the CPU from threads that still have work. It also waits in a
    SwitchToThread loop: each poll gives a whole time slice to another process, and
    a waiting thread then shows as Ready with almost no CPU time.

    Both settings are needed. With KMP_BLOCKTIME alone, two models in one process
    still stalled for minutes; with KMP_USE_YIELD alone a call still took 18 s.
    The price on an idle PC is about 0.08 s per translated sentence. Whisper did not
    get slower.

    Call this before ctranslate2 loads. A value the user set is kept.
    """
    for name, value in _OPENMP_WAIT_SETTINGS.items():
        if name not in os.environ:
            os.environ[name] = value
            _backend_only_env.add(name)


def external_process_env():
    env = dict(os.environ)
    for name in _backend_only_env:
        env.pop(name, None)
    if is_linux_frozen():
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original:
            env["LD_LIBRARY_PATH"] = original
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def voice_worker_env():
    """The environment of a voice conversion worker, whose Torch also uses Intel OpenMP.

    A block arrives every 80 ms, well inside the 200 ms that the threads spin. On the
    measured PC, Seed-VC kept four threads busy (about 420% CPU, 124% with these
    settings) and converted fewer blocks in the same time.
    """
    env = external_process_env()
    for name, value in _OPENMP_WAIT_SETTINGS.items():
        env.setdefault(name, value)
    return env
