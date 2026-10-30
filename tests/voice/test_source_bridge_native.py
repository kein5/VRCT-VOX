"""Native control tests: owned processes and private PipeWire only."""
from contextlib import ExitStack
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux native helper")


def compile_helper(tmp_path, source, *, pipewire=False):
    path = ROOT / source
    assert path.is_file(), "native source helper is not implemented"
    flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "libpipewire-0.3"], text=True)) if pipewire else []
    binary = tmp_path / ("gate" if pipewire else "launcher")
    subprocess.run(["cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", str(path), "-o", str(binary), *flags], check=True)
    return binary


@pytest.mark.parametrize("fault", [None, "marker", "class", "name", "serial", "cookie", "duplicate"])
def test_stream_gate_binds_only_expected_identity(tmp_path, fault):
    from tools.voice_acceptance import graph_snapshot, nodes, private_graph, start_process, wait_for
    gate = compile_helper(tmp_path, "native/voice-gate/main.c", pipewire=True)
    tag = "b" * 32
    name = f"vrct.source-bridge.{tag}.playback"
    actual_name = name + ".other" if fault == "name" else name
    with private_graph(config_fragment=ROOT / "config/pipewire/90-vrct-managed.conf"), ExitStack() as stack:
        destination = nodes()["vrct.managed.vc"]["info"]["props"]["object.serial"]

        def create(index):
            marker = "invalid" if fault == "marker" else "v1"
            media = "Audio/Source" if fault == "class" else "Stream/Output/Audio"
            start_process(stack, ["pw-loopback", "--channels", "1", "--channel-map", "MONO",
                "--capture-props", f"media.class=Audio/Sink node.name=bridge.test.{index}",
                "--playback-props", f"node.name={actual_name} media.class={media} target.object={destination} vrct.source.bridge={marker} node.param.Props={{mute=true}}"], stdout=subprocess.DEVNULL)

        create(0)
        wait_for(lambda: actual_name in nodes())
        if fault == "duplicate":
            create(1)
            wait_for(lambda: len([n for n in graph_snapshot() if n.get("info", {}).get("props", {}).get("node.name") == name]) == 2)
        before = nodes()[actual_name]
        serial = before["info"]["props"]["object.serial"] + (1 if fault == "serial" else 0)
        cookie = next(n["info"]["cookie"] for n in graph_snapshot() if n["type"] == "PipeWire:Interface:Core") + (1 if fault == "cookie" else 0)
        result = subprocess.run([str(gate), str(cookie), str(serial), "0", tag], timeout=3)
        assert (result.returncode == 0) is (fault is None)
        props = nodes()[actual_name]["info"]["params"]["Props"]
        assert next(p["mute"] for p in props if "mute" in p) is (fault is not None)


def test_legacy_managed_gate_contract_still_works(tmp_path):
    from models.audio_routing.pipewire_gate import PipeWireGate
    from tools.voice_acceptance import private_graph
    gate = compile_helper(tmp_path, "native/voice-gate/main.c", pipewire=True)
    with private_graph(config_fragment=ROOT / "config/pipewire/90-vrct-managed.conf"):
        control = PipeWireGate(helper=gate)
        before = control.inspect()
        assert control.set_muted(False, before["identity"])["muted"] is False
        assert control.set_muted(True, before["identity"])["muted"] is True


@pytest.mark.parametrize("args", [[], ["1", "1", "0", "short"], ["1", "1", "0", "G" * 32], ["-1", "1", "0"], ["1", "1", "no"]])
def test_gate_rejects_invalid_cli(tmp_path, args):
    gate = compile_helper(tmp_path, "native/voice-gate/main.c", pipewire=True)
    assert subprocess.run([str(gate), *args], timeout=3).returncode == 2


@pytest.mark.parametrize("args", [[], ["x"], ["-1"], ["0"], ["99999999"]])
def test_launcher_rejects_missing_or_wrong_parent(tmp_path, args):
    launcher = compile_helper(tmp_path, "native/source-bridge/main.c")
    assert subprocess.run([str(launcher), *args], timeout=2).returncode != 0


@pytest.mark.parametrize("mode", ["normal", "kill", "thread", "supervisor"])
def test_launcher_child_cannot_outlive_creating_parent_or_thread(tmp_path, mode):
    from tools.voice_acceptance import wait_for
    launcher = compile_helper(tmp_path, "native/source-bridge/main.c")
    fake = tmp_path / "pw-loopback"
    fake.write_text("#!/bin/sh\nexec " + shutil.which("sleep") + " 30\n")
    fake.chmod(0o700)
    script = """
import os, subprocess, sys, threading, time
mode, launcher = sys.argv[1:]
leave = threading.Event()
def launch():
    fd = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
    try:
        child = subprocess.Popen([launcher, str(os.getpid()), str(fd)], pass_fds=(fd,), stdout=subprocess.PIPE, text=True)
    finally:
        os.close(fd)
    print(child.stdout.readline().strip(), flush=True)
    if mode == 'thread': leave.wait()
    if mode == 'supervisor':
        input()
        child.kill()
        child.wait(timeout=2)
        print('supervisor-ended', flush=True)
        time.sleep(30)
if mode == 'thread':
    thread = threading.Thread(target=launch)
    thread.start()
    input()
    leave.set()
    thread.join()
    print('thread-ended', flush=True)
    time.sleep(30)
else:
    launch()
    input()
"""
    parent = subprocess.Popen([sys.executable, "-u", "-c", script, mode, str(launcher)],
                              env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    child = None
    try:
        pid = int(parent.stdout.readline())
        child = psutil.Process(pid)
        wait_for(lambda: child.name() == "sleep", timeout=3)
        if mode == "kill":
            parent.kill()
        else:
            parent.stdin.write("go\n")
            parent.stdin.flush()
        if mode in ('thread', 'supervisor'):
            assert parent.stdout.readline().strip() == mode + '-ended'
            assert parent.poll() is None
        else:
            parent.wait(timeout=3)
        wait_for(lambda: not child.is_running() or child.status() == psutil.STATUS_ZOMBIE, timeout=3)
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.communicate(timeout=3)
        if child and child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
            child.kill()


def test_creator_death_before_launcher_main_cannot_leave_audio_child(tmp_path):
    """Deterministically pause before prctl; the creating thread then exits."""
    launcher = compile_helper(tmp_path, 'native/source-bridge/main.c')
    preload = tmp_path / 'pause.c'
    preload.write_text('#include <signal.h>\n#include <stdlib.h>\n'
                       '__attribute__((constructor)) static void pause_main(void) {'
                       'unsetenv("LD_PRELOAD"); raise(SIGSTOP); }\n')
    library = tmp_path / 'pause.so'
    subprocess.run(['cc', '-shared', '-fPIC', str(preload), '-o', str(library)], check=True)
    fake = tmp_path / 'pw-loopback'
    fake.write_text('#!/bin/sh\nexec ' + shutil.which('sleep') + ' 30\n')
    fake.chmod(0o700)
    script = '''
import os, signal, subprocess, sys, threading
launcher, library = sys.argv[1:]
owned = []
def create():
    fd = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
    try:
        child = subprocess.Popen([launcher, str(os.getpid()), str(fd)], pass_fds=(fd,),
                                  env={**os.environ, 'LD_PRELOAD': library})
        owned.append(child)
        pid, status = os.waitpid(child.pid, os.WUNTRACED)
        assert os.WIFSTOPPED(status)
    finally:
        os.close(fd)
thread = threading.Thread(target=create)
thread.start(); thread.join()
child = owned[0]
try:
    child.send_signal(signal.SIGCONT)
    try:
        code = child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        sys.exit(4)
    assert code != 0
finally:
    if child.poll() is None: child.kill()
    child.wait(timeout=2)
'''
    result = subprocess.run([sys.executable, '-c', script, str(launcher), str(library)],
                            env={**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH']},
                            capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stderr or 'child survived creator before guard installation'
