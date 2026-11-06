"""Real NSIS update fault tests. Stdlib only except the separate --mode gui run.

Run --mode prepare only in the disposable CI checkout: it rewrites that checkout's
release URL and makes build stubs. No production URL override is introduced.
"""

import argparse
from contextlib import contextmanager
import ctypes
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import threading
import time
import zipfile


ROOT = Path(__file__).resolve().parents[2]
RELEASE_URL = "https://github.com/kein5/VRCT-VOX/releases/download/$release_revision"
APP = "vrct-vox.exe"
SIDECAR = "vrct-vox-sidecar.exe"
PACKAGE = "VRCT-VOX.zip"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\VRCT-VOX"
PRODUCT_KEY = r"Software\kein5\VRCT-VOX"


def payload_files(version):
    return {
        APP: f"{version} executable stub".encode(),
        SIDECAR: f"{version} sidecar stub".encode(),
        "_internal/shared.txt": f"{version} dependency".encode(),
        f"_internal/{version}-only.txt": f"{version} only".encode(),
        "_internal/nested/padding.bin": bytes(range(256)) * 2048,
    }


def archive_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return stream.getvalue()


def payloads():
    new = payload_files("new")
    good = archive_bytes(new)
    partial = bytearray(good)
    with zipfile.ZipFile(io.BytesIO(good)) as archive:
        info = archive.getinfo("_internal/new-only.txt")
        name_len, extra_len = struct.unpack_from("<HH", good, info.header_offset + 26)
        partial[info.header_offset + 30 + name_len + extra_len] ^= 0xFF
    return {
        "old": archive_bytes(payload_files("old")),
        "new": good,
        "checksum-404": good,
        "invalid-checksum": good,
        "hash-mismatch": good,
        "corrupt": b"This is not an archive.",
        "partial": bytes(partial),
        "no-exe": archive_bytes({k: v for k, v in new.items() if k != APP}),
        "no-internal": archive_bytes({k: v for k, v in new.items() if not k.startswith("_internal/")}),
        "range-fallback": good,
    }


class PackageServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port):
        super().__init__(("127.0.0.1", port), PackageHandler)
        self.payloads = payloads()
        self.requests = []
        self.request_lock = threading.Lock()


class PackageHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_HEAD(self):
        self.respond(head=True)

    def do_GET(self):
        self.respond(head=False)

    def respond(self, head):
        parts = self.path.strip("/").split("/")
        version = parts[0].removeprefix("v")
        range_header = self.headers.get("Range")
        with self.server.request_lock:
            self.server.requests.append({"method": self.command, "path": self.path, "range": range_header})
        if len(parts) != 2 or version not in self.server.payloads:
            self.send_error(404)
            return
        data = self.server.payloads[version]
        if parts[1] == PACKAGE + ".sha256":
            if version == "checksum-404":
                self.send_error(404)
                return
            data = sha256(data).hexdigest().encode()
            if version == "invalid-checksum":
                data = b"invalid"
            elif version == "hash-mismatch":
                data = b"0" * 64
        elif parts[1] != PACKAGE:
            self.send_error(404)
            return
        status, start, end = 200, 0, len(data) - 1
        if range_header:
            if version == "range-fallback" and range_header.startswith("bytes=0-"):
                self.send_error(416)
                return
            bounds = range_header.removeprefix("bytes=").split("-", 1)
            start, end = int(bounds[0]), int(bounds[1]) if bounds[1] else len(data) - 1
            if start > end or end >= len(data):
                self.send_error(416)
                return
            status = 206
        self.send_response(status)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.end_headers()
        if not head:
            try:
                # Keep sibling requests alive long enough to require cancellation.
                for offset in range(start, end + 1, 8192):
                    if version == "range-fallback" and range_header:
                        time.sleep(0.2)
                    self.wfile.write(data[offset:min(offset + 8192, end + 1)])
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass


@contextmanager
def serve(port, log):
    server = PackageServer(port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        log.write_text(json.dumps(server.requests, indent=2), encoding="utf-8")


def snapshot(directory):
    """Include empty directories as well as every file's path and hash."""
    return {p.relative_to(directory).as_posix(): "directory" if p.is_dir() else sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*"))}


def assert_tree(directory, expected):
    actual = snapshot(directory)
    assert actual == expected, json.dumps({
        "missing": sorted(expected.keys() - actual.keys()),
        "extra": sorted(actual.keys() - expected.keys()),
        "changed": sorted(k for k in actual.keys() & expected.keys() if actual[k] != expected[k]),
    }, indent=2)
    assert not (directory / ".upd").exists(), "Transaction work folder was retained"


def prepare(port):
    template = ROOT / "src-tauri/nsis/template.nsi"
    source = template.read_text(encoding="utf-8")
    assert source.count(RELEASE_URL) == 1, "Run prepare exactly once in a disposable checkout"
    template.write_text(source.replace(RELEASE_URL, f"http://127.0.0.1:{port}/$release_revision"), encoding="utf-8")
    for name, data in {
        "dist/index.html": b"<!doctype html><title>Installer test stub</title>",
        "src-tauri/bin/vrct-vox-sidecar-x86_64-pc-windows-msvc.exe": b"sidecar build stub",
        "src-tauri/bin/_internal/stub.txt": b"resource build stub",
    }.items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def installer_command(installer, directory, version, silent=True):
    # NSIS requires /D last, without quotes even when its value contains spaces.
    flags = "/S " if silent else ""
    return f'"{installer}" {flags}/NS /UILANG=en /VERSION={version} /D={directory}'


def installer_environment(temp):
    temp.mkdir(parents=True, exist_ok=True)
    return dict(os.environ, TEMP=str(temp), TMP=str(temp))


def run_install(installer, directory, version, temp, success):
    result = subprocess.run(installer_command(installer, directory, version),
                            env=installer_environment(temp), timeout=180, check=False)
    assert result.returncode == (0 if success else 2), f"{version}: exit {result.returncode}"
    assert not list(temp.glob(PACKAGE + ".p*")), "Background transfer fragments remain"
    assert not (temp / PACKAGE).exists(), "Downloaded archive was not removed"
    assert not (temp / (PACKAGE + ".sha256")).exists(), "Checksum sidecar remains"


def add_user_data(directory):
    for name, value in {
        "config.json": '{"ui":"日本語","keep":true}',
        "weights/custom/model.bin": "private weights",
        "logs/session.log": "private log",
        "telemetry_state.json": '{"enabled":false}',
        "user.log": "keep log",
        "update.exe": "legacy updater",
    }.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    (directory / "weights/empty").mkdir()


def expect_updated(directory, before):
    expected = {k: v for k, v in before.items()
                if k not in (APP, SIDECAR, "update.exe", "_internal") and not k.startswith("_internal/")}
    for name, value in payload_files("new").items():
        expected[name] = sha256(value).hexdigest()
        for parent in Path(name).parents:
            if str(parent) != ".":
                expected[parent.as_posix()] = "directory"
    assert (directory / "uninstall.exe").is_file()
    expected["uninstall.exe"] = sha256((directory / "uninstall.exe").read_bytes()).hexdigest()
    assert_tree(directory, expected)


@contextmanager
def hold_file(path):
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0, None)  # no FILE_SHARE_DELETE
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def interrupted_commit(directory, checkpoint):
    work = directory / ".upd"
    for name in ("new", "old", "add", "discard"):
        (work / name).mkdir(parents=True)
    (work / "committing").touch()
    if checkpoint == "marker":
        return
    for name in ("uninstall.exe", "update.exe"):
        (directory / name).rename(work / "old" / name)
    if checkpoint == "uninstallers":
        return
    (directory / APP).rename(work / "old" / APP)
    if checkpoint == "exe-backup":
        return
    (directory / APP).write_bytes(payload_files("new")[APP])
    if checkpoint == "exe-replaced":
        return
    (directory / "_internal").rename(work / "old/_internal")
    (directory / "_internal").mkdir()
    (directory / "_internal/new-only.txt").write_bytes(b"interrupted")
    # Simulate a package entry absent from the old install.
    (work / "add/added.dll").touch()
    if checkpoint != "add-recorded":
        (directory / "added.dll").write_bytes(b"added")
    if checkpoint == "rollback-started":
        (directory / "added.dll").rename(work / "discard/added.dll")
        # Marker still present: rerunning rollback must tolerate this point.


def silent_scenarios(installer, work, server):
    baseline = work / "fresh install"
    run_install(installer, baseline, "old", work / "temp-fresh", True)
    for name, data in payload_files("old").items():
        assert (baseline / name).read_bytes() == data
    assert (baseline / "uninstall.exe").is_file()
    expected_fresh = {name: sha256(value).hexdigest() for name, value in payload_files("old").items()}
    expected_fresh.update({"_internal": "directory", "_internal/nested": "directory",
                          "uninstall.exe": sha256((baseline / "uninstall.exe").read_bytes()).hexdigest(),
                          "installer_language.txt": sha256(b"").hexdigest()})
    assert_tree(baseline, expected_fresh)
    print("PASS fresh install", flush=True)
    add_user_data(baseline)
    before = snapshot(baseline)

    def clone(name):
        directory = work / name
        shutil.copytree(baseline, directory)
        return directory

    updated = clone("update success")
    run_install(installer, updated, "new", work / "temp-success", True)
    expect_updated(updated, before)
    print("PASS update success and user data retention", flush=True)

    for version in ("checksum-404", "invalid-checksum", "hash-mismatch", "corrupt", "partial", "no-exe", "no-internal"):
        directory = clone(version)
        run_install(installer, directory, version, work / f"temp-{version}", False)
        assert_tree(directory, before)
        if version in ("corrupt", "partial", "no-exe", "no-internal"):
            assert (work / f"temp-{version}" / (PACKAGE + ".bad")).read_bytes() == server.payloads[version]
        print(f"PASS unchanged tree after {version}", flush=True)

    directory = clone("commit locked dependency")
    with hold_file(directory / "_internal/shared.txt"):
        run_install(installer, directory, "new", work / "temp-locked", False)
        assert_tree(directory, before)
    print("PASS rollback after executable replacement and locked dependency", flush=True)

    for checkpoint in ("marker", "uninstallers", "exe-backup", "exe-replaced", "add-recorded", "add-replaced", "rollback-started"):
        directory = clone("recovery-" + checkpoint)
        interrupted_commit(directory, checkpoint)
        run_install(installer, directory, "checksum-404", work / ("temp-recovery-" + checkpoint), False)
        assert_tree(directory, before)
        print(f"PASS interrupted commit recovery at {checkpoint}", flush=True)

    directory = clone("blocked recovery")
    interrupted_commit(directory, "exe-replaced")
    with hold_file(directory / APP):
        run_install(installer, directory, "checksum-404", work / "temp-blocked", False)
        assert (directory / ".upd/committing").exists()
        assert (directory / ".upd/old" / APP).read_bytes() == payload_files("old")[APP]
    run_install(installer, directory, "checksum-404", work / "temp-unblocked", False)
    assert_tree(directory, before)
    print("PASS blocked restoration retains backups and can be retried", flush=True)

    directory = clone("range fallback")
    run_install(installer, directory, "range-fallback", work / "temp-range", True)
    expect_updated(directory, before)
    requests = [r for r in server.requests if r["method"] == "GET" and r["path"] == "/vrange-fallback/" + PACKAGE]
    assert any(r["range"] for r in requests), "Parallel path not reached; check available disk space"
    assert any(r["range"] is None for r in requests), "Single-connection fallback not reached"
    print("PASS failed range falls back to a single connection", flush=True)

    fresh_failed = work / "failed fresh"
    run_install(installer, fresh_failed, "partial", work / "temp-fresh-failed", False)
    assert not fresh_failed.exists()
    print("PASS failed fresh install removes install folder", flush=True)


def register_old_install(directory):
    import winreg
    for path, values in {
        PRODUCT_KEY: {"": str(directory), "Installer Language": "1033"},
        UNINSTALL_KEY: {"": str(directory), "DisplayVersion": "0.0.1", "DisplayName": "VRCT-VOX",
                        "UninstallString": f'"{directory / "uninstall.exe"}"'},
    }.items():
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
            for name, value in values.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def gui_scenario(installer, work):
    from pywinauto import Desktop
    directory = work / "gui old install"
    run_install(installer, directory, "old", work / "temp-gui-seed", True)
    add_user_data(directory)
    before = snapshot(directory)
    register_old_install(directory)
    process = subprocess.Popen(installer_command(installer, directory, "checksum-404", silent=False),
                               env=installer_environment(work / "temp-gui"))
    desktop = Desktop(backend="win32")
    selected = False
    saw_failure = False
    deadline = time.monotonic() + 120
    events = []
    try:
        while process.poll() is None and time.monotonic() < deadline:
            windows = desktop.windows(process=process.pid, visible_only=True)
            for window in windows:
                text = "\n".join(control.window_text() for control in window.descendants())
                events.append(text)
                buttons = [b for b in window.descendants(class_name="Button") if b.is_visible() and b.is_enabled()]
                uninstall_choice = [b for b in buttons if "uninstall before installing" in b.window_text().replace("&", "").lower()]
                if uninstall_choice:
                    # The default first radio must still be selected on arrival.
                    assert uninstall_choice[0].get_check_state() == 1
                    uninstall_choice[0].click()
                    selected = True
                if "Could not download the package checksum" in text:
                    saw_failure = True
                for caption in ("OK", "I Agree", "Next >", "Install", "Close", "Finish"):
                    matches = [b for b in buttons if b.window_text().replace("&", "").strip() == caption]
                    if matches:
                        matches[0].click()
                        time.sleep(0.2)
                        break
            time.sleep(0.1)
        assert process.poll() is not None, "Wizard timed out"
        assert process.returncode == 2, f"GUI failure exit: {process.returncode}"
        assert selected, "The upgrade maintenance choice was never reached"
        assert saw_failure, "The checksum failure dialog was never reached"
        assert_tree(directory, before)
        print("PASS default wizard uninstall-before-installing preserves old tree", flush=True)
    finally:
        (work / "gui-controls.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def verify_partial_fixture(work):
    archive = work / "partial-fixture.zip"
    archive.write_bytes(payloads()["partial"])
    destination = work / "partial-probe"
    destination.mkdir()
    result = subprocess.run(["tar", "-xvf", str(archive), "-C", str(destination)],
                            capture_output=True, timeout=30, check=False)
    (work / "partial-probe.log").write_bytes(result.stdout + result.stderr)
    assert result.returncode != 0, "Fixture must cause a real tar extraction error"
    assert (destination / APP).is_file(), "Fixture must fail after writing the executable"
    assert (destination / "_internal/shared.txt").is_file(), "Fixture must partially extract dependencies"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "silent", "gui"), required=True)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--work-dir", type=Path, default=ROOT / ".review/tmp/windows-update")
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.port)
        return
    if os.name != "nt":
        parser.error("Real installer scenarios require Windows")
    if args.installer is None or not args.installer.is_file():
        parser.error("--installer must name the built NSIS executable")
    work = args.work_dir.resolve() / args.mode
    work.mkdir(parents=True, exist_ok=False)
    with serve(args.port, work / "http-requests.json") as server:
        if args.mode == "silent":
            verify_partial_fixture(work)
            silent_scenarios(args.installer.resolve(), work, server)
        else:
            gui_scenario(args.installer.resolve(), work)


if __name__ == "__main__":
    main()
