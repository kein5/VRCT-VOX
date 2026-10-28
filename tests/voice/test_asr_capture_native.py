from contextlib import ExitStack
import os
from pathlib import Path
import select
import shlex
import subprocess
import sys
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux capture helper")


def build(tmp_path):
    source = ROOT / "native/asr-capture/main.c"
    assert source.is_file(), "native capture is not implemented"
    binary = tmp_path / "capture"
    flags = shlex.split(
        subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "libpipewire-0.3"], text=True
        )
    )
    subprocess.run(
        [
            "cc",
            "-std=gnu11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
            *flags,
            "-lm",
        ],
        check=True,
    )
    return binary


def test_capture_rejects_invalid_cli_before_connecting(tmp_path):
    binary = build(tmp_path)
    for args in ([], ["1", "1", "1", "1", "name", "mic", "tag"]):
        assert subprocess.run([str(binary), *args], timeout=2).returncode != 0


@pytest.mark.parametrize("source_kind", ["mic", "speaker"])
def test_private_capture_has_timestamped_pcm_and_stops_on_target_removal(
    tmp_path, source_kind
):
    binary = build(tmp_path)
    from models.transcription.capture_packets import CapturePackets
    from tools.voice_acceptance import (
        private_graph,
        loopback,
        graph_snapshot,
        nodes,
        stop_process,
    )
    from tools.voice_b_poc import Producer, ToneCapture, ready

    with private_graph(), ExitStack() as stack:
        endpoint_process = loopback(stack, "vrct.capture.test")
        Producer(stack, "vrct.capture.test.sink", 440)
        # Producer construction only launches pw-cat; its asynchronous link and
        # latency propagation can still be pending. Establish actual signal flow
        # before testing timestamp continuity and target removal on a fixed graph.
        probe = ToneCapture(stack, "vrct.capture.test.source")
        ready(probe, 440)
        name = "vrct.capture.test." + ("source" if source_kind == "mic" else "sink")
        snapshot = graph_snapshot()
        cookie = next(
            n["info"]["cookie"]
            for n in snapshot
            if n["type"] == "PipeWire:Interface:Core"
        )
        serial = nodes()[name]["info"]["props"]["object.serial"]
        owner = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
        try:
            p = subprocess.Popen(
                [
                    str(binary),
                    str(os.getpid()),
                    str(owner),
                    str(cookie),
                    str(serial),
                    name,
                    source_kind,
                    "a" * 32,
                ],
                pass_fds=(owner,),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        finally:
            os.close(owner)
        try:
            d = CapturePackets()
            received = []
            deadline = time.monotonic() + 5
            while len(received) < 10 and time.monotonic() < deadline:
                if select.select([p.stdout], [], [], 0.1)[0]:
                    raw = os.read(p.stdout.fileno(), 4096)
                    assert raw, p.stderr.read().decode()
                    received.extend(d.feed(raw, time.monotonic_ns()))
                assert p.poll() is None
            assert len(received) >= 10
            assert any(any(frame.audio.pcm) for frame in received)
            stop_process(endpoint_process)
            assert p.wait(2) != 0
        finally:
            stop_process(p)
            p.stdout.close()
            p.stderr.close()


def test_advancing_graph_cycle_is_same_epoch_but_not_same_snapshot(tmp_path):
    """Different buffers advance cycle; only paired reads need equal cycles."""
    harness = tmp_path / "clock.c"
    harness.write_text(
        '#include <assert.h>\n#define main capture_main\n#include "'
        + str(ROOT / "native/asr-capture/main.c")
        + '"\n#undef main\n'
        "int main(void) { struct spa_io_clock a={.id=15,.rate={1,48000},.duration=256,.cycle=2,.nsec=100}; "
        "struct spa_io_clock b=a; b.cycle++; b.nsec+=5333333; "
        "return same_clock(&a,&b,false) && !same_clock(&a,&b,true) ? 0 : 1; }\n"
    )
    flags = shlex.split(
        subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "libpipewire-0.3"], text=True
        )
    )
    executable = tmp_path / "clock"
    subprocess.run(
        [
            "cc",
            "-std=gnu11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(harness),
            "-o",
            str(executable),
            *flags,
            "-lm",
        ],
        check=True,
    )
    assert subprocess.run([str(executable)], capture_output=True).returncode == 0


@pytest.mark.parametrize("fault", ["cookie", "serial", "backpressure"])
def test_capture_fails_closed_for_wrong_identity_or_unread_pipe(tmp_path, fault):
    binary = build(tmp_path)
    from tools.voice_acceptance import (
        private_graph,
        loopback,
        graph_snapshot,
        nodes,
        stop_process,
    )
    from tools.voice_b_poc import Producer

    with private_graph(), ExitStack() as stack:
        loopback(stack, "vrct.capture.fault")
        Producer(stack, "vrct.capture.fault.sink", 440)
        snapshot = graph_snapshot()
        cookie = next(
            n["info"]["cookie"]
            for n in snapshot
            if n["type"] == "PipeWire:Interface:Core"
        )
        serial = nodes()["vrct.capture.fault.source"]["info"]["props"]["object.serial"]
        owner = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
        try:
            p = subprocess.Popen(
                [
                    str(binary),
                    str(os.getpid()),
                    str(owner),
                    str(cookie + (fault == "cookie")),
                    str(serial + (fault == "serial")),
                    "vrct.capture.fault.source",
                    "mic",
                    "b" * 32,
                ],
                pass_fds=(owner,),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        finally:
            os.close(owner)
        try:
            # Deliberately don't drain stdout; bounded writes must fail, not wait.
            assert p.wait(4) != 0
            error = p.stderr.read()
            expected = {
                "cookie": b"core_changed",
                "serial": b"endpoint_changed",
                "backpressure": b"pipe_blocked",
            }[fault]
            assert expected in error, error
            if fault != "backpressure":
                assert not p.stdout.read()
        finally:
            stop_process(p)
            p.stdout.close()
            p.stderr.close()


@pytest.mark.parametrize("mode", ["normal", "kill", "thread"])
def test_capture_cannot_outlive_parent_or_creating_thread(tmp_path, mode):
    import psutil
    from tools.voice_acceptance import (
        private_graph,
        loopback,
        graph_snapshot,
        nodes,
        wait_for,
    )

    binary = build(tmp_path)
    script = """
import os, subprocess, sys, threading, time
binary, cookie, serial, mode = sys.argv[1:]
leave = threading.Event()
def create():
    fd = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
    try:
        child = subprocess.Popen([binary, str(os.getpid()), str(fd), cookie, serial,
            'vrct.capture.owner.source', 'mic', 'c'*32], pass_fds=(fd,),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    finally: os.close(fd)
    assert child.stdout.read(32)[:4] == b'VCA1'
    print(child.pid, flush=True)
    def drain():
        while child.stdout.read(4096): pass
    threading.Thread(target=drain, daemon=True).start()
    if mode == 'thread': leave.wait()
if mode == 'thread':
    t = threading.Thread(target=create); t.start()
    input(); leave.set(); t.join()
    print('thread-ended', flush=True)
    time.sleep(30)
else:
    create(); input()
"""
    with private_graph(), ExitStack() as stack:
        loopback(stack, "vrct.capture.owner")
        cookie = next(
            n["info"]["cookie"]
            for n in graph_snapshot()
            if n["type"] == "PipeWire:Interface:Core"
        )
        serial = nodes()["vrct.capture.owner.source"]["info"]["props"]["object.serial"]
        parent = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                script,
                str(binary),
                str(cookie),
                str(serial),
                mode,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        child = None
        try:
            assert select.select([parent.stdout], [], [], 5)[0], (
                "parent readiness timeout"
            )
            line = parent.stdout.readline().strip()
            assert line.isdigit(), parent.stderr.read()
            child = psutil.Process(int(line))
            if mode == "kill":
                parent.kill()
            else:
                parent.stdin.write("go\n")
                parent.stdin.flush()
            if mode == "thread":
                assert parent.stdout.readline().strip() == "thread-ended"
                assert parent.poll() is None
            else:
                parent.wait(timeout=2)
            try:
                wait_for(
                    lambda: not child.is_running()
                    or child.status() == psutil.STATUS_ZOMBIE,
                    timeout=2,
                )
            except psutil.NoSuchProcess:
                pass  # It exited between is_running() and status().
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.communicate(timeout=2)
            try:
                if child and child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                    child.kill()
            except psutil.NoSuchProcess:
                pass


def test_capture_never_follows_changed_default_or_same_name_recreation(tmp_path):
    from tools.voice_acceptance import (
        private_graph,
        loopback,
        graph_snapshot,
        nodes,
        stop_process,
        wait_for,
    )

    binary = build(tmp_path)
    with private_graph(), ExitStack() as stack:
        selected = loopback(stack, "vrct.capture.selected")
        loopback(stack, "vrct.capture.decoy")
        cookie = next(
            n["info"]["cookie"]
            for n in graph_snapshot()
            if n["type"] == "PipeWire:Interface:Core"
        )
        serial = nodes()["vrct.capture.selected.source"]["info"]["props"][
            "object.serial"
        ]
        fd = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
        try:
            p = subprocess.Popen(
                [
                    str(binary),
                    str(os.getpid()),
                    str(fd),
                    str(cookie),
                    str(serial),
                    "vrct.capture.selected.source",
                    "mic",
                    "d" * 32,
                ],
                pass_fds=(fd,),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        finally:
            os.close(fd)
        drain_stop = threading.Event()

        def drain():
            while not drain_stop.is_set():
                if select.select([p.stdout], [], [], 0.05)[0] and not os.read(
                    p.stdout.fileno(), 4096
                ):
                    break

        reader = threading.Thread(target=drain)
        reader.start()
        try:
            own_name = "vrct.asr.capture." + "d" * 32
            wait_for(lambda: own_name in nodes())
            subprocess.run(
                [
                    "pw-metadata",
                    "-n",
                    "default",
                    "0",
                    "default.audio.source",
                    '{"name":"vrct.capture.decoy.source"}',
                ],
                check=True,
                capture_output=True,
                timeout=2,
            )
            time.sleep(0.15)
            assert p.poll() is None
            graph = graph_snapshot()
            own = nodes()[own_name]["id"]
            target = nodes()["vrct.capture.selected.source"]["id"]
            inbound = [
                n["info"]["output-node-id"]
                for n in graph
                if n["type"] == "PipeWire:Interface:Link"
                and n["info"]["input-node-id"] == own
            ]
            assert inbound and set(inbound) == {target}
            stop_process(selected)
            loopback(stack, "vrct.capture.selected")
            assert (
                nodes()["vrct.capture.selected.source"]["info"]["props"][
                    "object.serial"
                ]
                != serial
            )
            assert p.wait(timeout=2) != 0
            wait_for(lambda: own_name not in nodes())
        finally:
            stop_process(p)
            drain_stop.set()
            reader.join(2)
            p.stdout.close()
            p.stderr.close()


@pytest.mark.parametrize("flag", ["header", "chunk"])
@pytest.mark.parametrize("started", [False, True])
def test_corrupted_buffer_never_emits_pcm(tmp_path, flag, started):
    """Removing either corruption check would send a syntactically valid packet."""
    harness = tmp_path / "corrupted.c"
    harness.write_text(
        '''
#define main capture_main
#define pw_stream_get_node_id fixture_node_id
#define pw_stream_get_time_n fixture_time
#include "'''
        + str(ROOT / "native/asr-capture/main.c")
        + """"
#undef main
static uint64_t cycle;
uint32_t fixture_node_id(struct pw_stream *stream) { (void)stream; return 7; }
int fixture_time(struct pw_stream *stream, struct pw_time *t, size_t size) {
    (void)stream; (void)size; *t=(struct pw_time){.now=cycle,.rate={1,48000}}; return 0;
}
int main(int argc, char **argv) {
    pw_init(&argc, &argv);
    cycle=now_ns()-1000000;
    struct spa_io_position position={.clock={.id=1,.rate={1,48000},.duration=480,.nsec=cycle}};
    struct state s={.target_ok=true,.n_links=1,.format_ok=true,.latency_ok=true,.own=7,
        .started=argv[2][0]=='1',.last_cycle=cycle-1,.position=&position,.epoch=position.clock};
    s.loop=pw_main_loop_new(NULL);
    struct spa_meta_header header={.flags=argv[1][0]=='h'?SPA_META_HEADER_FLAG_CORRUPTED:0};
    struct spa_meta meta={.type=SPA_META_Header,.size=sizeof(header),.data=&header};
    uint8_t pcm[960]={1};
    struct spa_chunk chunk={.size=960,.stride=2,.flags=argv[1][0]=='c'?SPA_CHUNK_FLAG_CORRUPTED:0};
    struct spa_data data={.data=pcm,.maxsize=960,.chunk=&chunk};
    struct spa_buffer buffer={.n_datas=1,.datas=&data,.n_metas=1,.metas=&meta};
    struct pw_buffer input={.buffer=&buffer,.time=cycle};
    bool sent=send_buffer(&s,&input);
    pw_main_loop_destroy(s.loop); pw_deinit();
    return !sent && s.stopping && s.result ? 0 : 3;
}
"""
    )
    flags = shlex.split(
        subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "libpipewire-0.3"], text=True
        )
    )
    binary = tmp_path / "corrupted"
    subprocess.run(
        [
            "cc",
            "-std=gnu11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(harness),
            "-o",
            str(binary),
            *flags,
            "-lm",
        ],
        check=True,
    )
    result = subprocess.run(
        [str(binary), flag, str(int(started))], capture_output=True, timeout=2
    )
    assert result.stdout == b"", "corrupted audio escaped as PCM packet"
    assert result.returncode == 0
    assert b"corrupted" in result.stderr


@pytest.mark.parametrize("started", [False, True])
def test_null_latency_invalidates_cached_value_and_stops_active_capture(
    tmp_path, started
):
    harness = tmp_path / "latency.c"
    harness.write_text(
        '''
#define main capture_main
#include "'''
        + str(ROOT / "native/asr-capture/main.c")
        + """"
#undef main
int main(int argc, char **argv) {
    pw_init(&argc,&argv);
    struct state s={.started=argv[1][0]=='1',.latency_ok=true,.latency={.max_quantum=2}};
    s.loop=pw_main_loop_new(NULL);
    stream_param(&s,SPA_PARAM_Latency,NULL);
    bool valid=!s.latency_ok && s.stopping==s.started && (!s.started || s.result!=0);
    pw_main_loop_destroy(s.loop); pw_deinit();
    return valid ? 0 : 3;
}
"""
    )
    flags = shlex.split(
        subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "libpipewire-0.3"], text=True
        )
    )
    binary = tmp_path / "latency"
    subprocess.run(
        [
            "cc",
            "-std=gnu11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(harness),
            "-o",
            str(binary),
            *flags,
            "-lm",
        ],
        check=True,
    )
    result = subprocess.run(
        [str(binary), str(int(started))], capture_output=True, timeout=2
    )
    assert result.returncode == 0, "NULL latency left previous timing epoch usable"
    assert result.stdout == b""
