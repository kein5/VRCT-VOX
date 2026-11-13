"""What a usage event says about the PC: its CPU, memory and GPUs, with each GPU's driver version.

The names come from the bundled speech.cpp (`speech devices --json`), the list the model
guidance already uses. Nothing here reads a serial number, a host or user name, or an audio
device. Memory is sent as the nearest common size, not the exact amount.
"""
import json
import os
import re
import subprocess
import sys
from threading import Lock

TIMEOUT = 3.0
MAX_GPUS = 4
NAME_LIMIT = 64
# Installed memory comes in these sizes (GiB); the nearest one is sent.
MEMORY_STEPS_GB = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024)
_GIB = 2 ** 30
_DRIVER = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}")
# The display adapters' class in the Windows registry; each adapter has a numbered key.
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_lock = Lock()
_cached = None


def ascii_text(value, limit=NAME_LIMIT):
    """A name from a driver or the OS as an event may carry it, or "" when nothing is left.

    Whatever is not printable ASCII is dropped, so text in another script never travels.
    """
    if not isinstance(value, str):
        return ""
    kept = "".join(char if " " <= char <= "~" else " " if char.isspace() else "" for char in value)
    return " ".join(kept.split())[:limit].strip()


def memory_step(size):
    """The common memory size, in GiB, nearest to a number of bytes."""
    return min(MEMORY_STEPS_GB, key=lambda step: abs(step * _GIB - size))


def _devices(timeout):
    """The rows of `speech devices --json`: name, description, kind, memory_total."""
    from models.model_downloads.hardware import parse_devices
    from models.speech_server.runtime import bundled_binary
    from runtime_paths import external_process_env
    done = subprocess.run([str(bundled_binary()), "devices", "--json"], stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                          env=dict(external_process_env(), SPEECH_NO_UPDATE_CHECK="1", NO_COLOR="1"),
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0 or len(done.stdout) > 65536:
        return []
    return parse_devices(json.loads(done.stdout))


def _windows_drivers():
    """{an adapter's name: its driver's version}, as Device Manager shows them."""
    import winreg
    found = {}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS) as root:
        for index in range(64):
            try:
                with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                    name = winreg.QueryValueEx(key, "DriverDesc")[0]
                    version = winreg.QueryValueEx(key, "DriverVersion")[0]
            except OSError as error:
                if getattr(error, "winerror", None) == 259:  # No more keys.
                    break
                continue  # A key without these values, or one this user may not read.
            if isinstance(name, str) and isinstance(version, str):
                found.setdefault(name, version)
    return found


def _linux_drivers(names):
    """Only NVIDIA's own driver names its version in one place; Mesa's is not read."""
    with open("/sys/module/nvidia/version", encoding="ascii") as stream:
        version = stream.read(64).strip()
    return {name: version for name in names if "nvidia" in name.lower()}


def _drivers(names):
    try:
        if sys.platform == "win32":
            return _windows_drivers()
        if sys.platform.startswith("linux"):
            return _linux_drivers(names)
    except Exception:
        pass
    return {}


def collect(timeout=TIMEOUT):
    """{"cpu", "cores", "ram_gb", "gpus": [{"name", "kind", "vram_gb", "driver"}]}, each only when known."""
    hardware = {}
    try:
        rows = _devices(timeout)
    except Exception:
        rows = []
    cpu = next((row for row in rows if row["kind"] == "cpu"), None)
    if cpu is not None and ascii_text(cpu["description"]):
        hardware["cpu"] = ascii_text(cpu["description"])
    cores = os.cpu_count()
    if type(cores) is int and 1 <= cores <= 4096:
        hardware["cores"] = cores
    if cpu is not None and cpu["memory_total"]:
        hardware["ram_gb"] = memory_step(cpu["memory_total"])
    if rows:
        adapters = [row for row in rows if row["kind"] in ("gpu", "igpu") and ascii_text(row["description"])][:MAX_GPUS]
        drivers = _drivers([row["description"] for row in adapters]) if adapters else {}
        gpus = []
        for row in adapters:
            gpu = {"name": ascii_text(row["description"]), "kind": row["kind"]}
            if row["memory_total"]:
                gpu["vram_gb"] = max(1, min(1024, round(row["memory_total"] / _GIB)))
            driver = drivers.get(row["description"])
            if driver is None:
                # A layer over the adapter's own driver names it inside its own name,
                # as "Microsoft Direct3D12 (NVIDIA GeForce RTX 3060 Ti)" does.
                inside = [name for name in drivers if name and name in row["description"]]
                driver = drivers[max(inside, key=len)] if inside else None
            if isinstance(driver, str) and _DRIVER.fullmatch(driver):
                gpu["driver"] = driver
            gpus.append(gpu)
        hardware["gpus"] = gpus
    return hardware


def cached(timeout=TIMEOUT):
    """collect(), once for the process: the hardware does not change while the app runs."""
    global _cached
    with _lock:
        if _cached is None:
            _cached = collect(timeout)
        return json.loads(json.dumps(_cached))
