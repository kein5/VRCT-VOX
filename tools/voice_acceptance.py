"""Repeatable Linux P1 measurements on a private PipeWire graph.

Only synthetic audio is captured, counted and discarded. No physical devices,
desktop defaults, microphone samples, or speech text are included in reports.
Run with uv run --no-project python tools/voice_acceptance.py --help.
"""
import argparse
from contextlib import ExitStack, contextmanager
import csv
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from threading import Lock, Thread
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src-python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.audio_routing.audio_router import AudioRouter  # noqa: E402
from models.tts.settings import VoiceSettings, local_url  # noqa: E402
from models.tts.speechcpp_tts import SpeechCppTTS  # noqa: E402
from models.tts.tts_scheduler import VoiceEventBus  # noqa: E402
from models.voice_events import AudioFrame, SpeechMessageEvent  # noqa: E402
from tools.voice_latency import summarize  # noqa: E402


# No ALSA, Bluetooth, PulseAudio, camera, or device enumeration modules.
PIPEWIRE_CONFIG = """
context.properties = {
    core.daemon = true
    core.name = vrct-acceptance
    default.clock.rate = 48000
    default.clock.quantum = 256
}
context.spa-libs = {
    audio.convert.* = audioconvert/libspa-audioconvert
    support.* = support/libspa-support
}
context.modules = [
    { name = libpipewire-module-rt flags = [ ifexists nofail ] }
    { name = libpipewire-module-protocol-native }
    { name = libpipewire-module-metadata }
    { name = libpipewire-module-spa-node-factory }
    { name = libpipewire-module-client-node }
    { name = libpipewire-module-access }
    { name = libpipewire-module-adapter }
    { name = libpipewire-module-link-factory }
]
context.objects = [
    { factory = spa-node-factory args = {
        factory.name = support.node.driver
        node.name = Dummy-Driver
        node.group = pipewire.dummy
        priority.driver = 20000
    } }
]
"""


def wait_for(predicate, timeout=5, code="acceptance_condition_timeout"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise TimeoutError(code)


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def start_process(stack, command, **kwargs):
    process = subprocess.Popen(command, stderr=subprocess.DEVNULL, **kwargs)
    stack.callback(stop_process, process)
    return process


def graph_snapshot():
    data = subprocess.run(["pw-dump"], capture_output=True, check=True, timeout=3)
    return json.loads(data.stdout)


def nodes():
    return {n["info"]["props"].get("node.name"): n for n in graph_snapshot()
            if n["type"] == "PipeWire:Interface:Node"}


def default_output():
    for node in graph_snapshot():
        if node.get("props", {}).get("metadata.name") == "default":
            for entry in node.get("metadata", []):
                if entry["key"] == "default.audio.sink":
                    return entry["value"].get("name")
    return None


@contextmanager
def private_graph():
    """Isolate both sockets and policy state; restore environment after workers exit."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError("linux_required")
    for binary in ("pipewire", "wireplumber", "pw-loopback", "pw-cat", "pw-dump", "pw-metadata"):
        if not shutil.which(binary):
            raise RuntimeError(f"missing_{binary}")
    with tempfile.TemporaryDirectory(prefix="vrct-p1-") as directory, ExitStack() as stack:
        root = Path(directory)
        config = root / "acceptance.conf"
        config.write_text(PIPEWIRE_CONFIG, encoding="utf-8")
        overrides = {"PIPEWIRE_RUNTIME_DIR": directory, "PIPEWIRE_REMOTE": "vrct-acceptance",
                     "XDG_STATE_HOME": str(root / "state"), "XDG_CONFIG_HOME": str(root / "config"),
                     "WIREPLUMBER_CONFIG_DIR": "/usr/share/wireplumber"}
        old = {key: os.environ.get(key) for key in overrides}
        os.environ.update(overrides)

        def restore():
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        stack.callback(restore)
        daemon = start_process(stack, ["pipewire", "-c", str(config)], stdout=subprocess.DEVNULL)
        wait_for(lambda: (root / "vrct-acceptance").exists() or daemon.poll() is not None)
        if daemon.poll() is not None:
            raise RuntimeError("private_pipewire_failed")
        policy = start_process(stack, ["wireplumber", "--profile", "policy"], stdout=subprocess.DEVNULL)
        # Wait for the policy client to appear before creating devices.
        def policy_ready():
            data = subprocess.run(["pw-dump"], capture_output=True, check=True, timeout=3)
            return any(str(n.get("info", {}).get("props", {}).get("application.process.id")) == str(policy.pid)
                       for n in json.loads(data.stdout))
        wait_for(policy_ready, code="private_policy_not_ready")
        if policy.poll() is not None:
            raise RuntimeError("private_policy_failed")
        yield stack


def loopback(stack, name):
    process = start_process(stack, [
        "pw-loopback", "--name", name, "--channels", "1", "--channel-map", "MONO",
        "--capture-props", f"media.class=Audio/Sink node.name={name}.sink node.virtual=true",
        "--playback-props", f"media.class=Audio/Source node.name={name}.source node.virtual=true node.passive=true",
    ], stdout=subprocess.DEVNULL)
    wait_for(lambda: {f"{name}.sink", f"{name}.source"} <= nodes().keys())
    return process


class PCMObservation:
    """Counters only, updated by one reader; reset between fully drained jobs."""
    def __init__(self):
        self.lock = Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.state = {"bytes": 0, "nonzero_chunks": 0, "first_nonzero_ns": None,
                          "last_nonzero_ns": None, "last_read_ns": None}

    def feed(self, pcm, timestamp_ns):
        with self.lock:
            self.state["bytes"] += len(pcm)
            self.state["last_read_ns"] = timestamp_ns
            if any(pcm):
                self.state["nonzero_chunks"] += 1
                if self.state["first_nonzero_ns"] is None:
                    self.state["first_nonzero_ns"] = timestamp_ns
                self.state["last_nonzero_ns"] = timestamp_ns

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def quiet(self, since_ns, duration_ms=150):
        state = self.snapshot()
        # Require continued capture after the last nonzero sample, not a dead reader.
        end = state["last_read_ns"] or 0
        return end - max(since_ns, state["last_nonzero_ns"] or 0) >= duration_ms * 1e6


class Capture(PCMObservation):
    def __init__(self, stack, target):
        super().__init__()
        self.process = start_process(stack, [
            "pw-cat", "--record", "--raw", "--format", "s16", "--rate", "48000",
            "--channels", "1", "--latency", "10ms", "--target", target,
            "--properties", "{ node.dont-fallback=true node.dont-reconnect=true }", "-",
        ], stdout=subprocess.PIPE)
        self.thread = Thread(target=self.read, daemon=True)
        self.thread.start()
        stack.callback(self.close)
        wait_for(lambda: self.snapshot()["bytes"] > 0, code="capture_not_ready")

    def read(self):
        while pcm := self.process.stdout.read1(960):
            self.feed(pcm, time.monotonic_ns())

    def close(self):
        stop_process(self.process)
        self.thread.join(2)
        self.process.stdout.close()


class TimedRouter(AudioRouter):
    def __init__(self):
        super().__init__()
        self.first_write_ns = None

    def play(self, frames, device, token, on_first_audio):
        self.first_write_ns = None

        def first(timestamp, rate):
            self.first_write_ns = timestamp
            on_first_audio(timestamp, rate)
        return super().play(frames, device, token, first)


class ToneProvider:
    """Deterministic sustained signal for stop/hotplug; no inference benchmark."""
    def __init__(self, _url):
        pass

    def synthesize_stream(self, text, voice, language, token):
        for _ in range(1000):
            token.check()
            yield AudioFrame(b"\x00\x10\x00\xf0" * 240, 48000)


def make_event(number):
    return SpeechMessageEvent(str(number), "chat", "こんにちは。音声の接続テストです。", source_language="ja")


def idle(bus):
    status = bus.status()
    return status if not status["active"] and not status["queued"] else None


def exercise_routes(stack, capture, target_process, decoy, server=None):
    settings = VoiceSettings(mode="original", output_device="vrct.test.sink",
                             japanese_url=server or "http://127.0.0.1:8080")
    bus = VoiceEventBus(settings, provider_factory=SpeechCppTTS if server else ToneProvider)
    stack.callback(bus.close)
    bus.publish(make_event("cancel"))
    wait_for(lambda: capture.snapshot()["nonzero_chunks"] > 5)
    for i in range(20):
        bus.publish(make_event(f"queued-{i}"))
    before = bus.status()
    stopped_ns = time.monotonic_ns()
    bus.cancel()
    cancelled = wait_for(lambda: idle(bus))
    idle_ns = time.monotonic_ns()
    wait_for(lambda: capture.quiet(stopped_ns), timeout=2)
    observed = capture.snapshot()
    if cancelled["cancelled"] != 1 or before["queued"] != 4 or cancelled["queued"]:
        raise RuntimeError("cancel_or_queue_failed")
    cancel = {"queue_before": before["queued"], "overflow_dropped": before["dropped"],
              "queue_after": cancelled["queued"], "cancel_to_idle_ms": (idle_ns - stopped_ns) / 1e6,
              "last_nonzero_after_cancel_ms": max(0, ((observed["last_nonzero_ns"] or 0) - stopped_ns) / 1e6),
              "continued_silence_observed_ms": (observed["last_read_ns"] - max(stopped_ns, observed["last_nonzero_ns"])) / 1e6}
    capture.reset()
    bus.publish(make_event("disconnect"))
    wait_for(lambda: capture.snapshot()["nonzero_chunks"] > 5)
    removed_ns = time.monotonic_ns()
    stop_process(target_process)
    failed = wait_for(lambda: idle(bus), timeout=5)
    if failed["errors"] != 1 or failed["completed"]:
        raise RuntimeError("disconnect_not_detected")
    disconnect_ms = (time.monotonic_ns() - removed_ns) / 1e6
    bus.publish(make_event("missing"))
    missing = wait_for(lambda: idle(bus), timeout=5)
    if missing["errors"] != 2 or missing["last_error"] != "output_missing":
        raise RuntimeError("missing_target_not_rejected")
    loopback(stack, "vrct.test")
    recovered_capture = Capture(stack, "vrct.test.source")
    bus.configure(settings)  # Explicit reselect, then a new event.
    bus.publish(make_event("recover"))
    wait_for(lambda: recovered_capture.snapshot()["nonzero_chunks"] > 5)
    bus.cancel()
    wait_for(lambda: idle(bus))
    since = time.monotonic_ns()
    wait_for(lambda: decoy.quiet(since), code="decoy_capture_stopped")
    if decoy.snapshot()["nonzero_chunks"]:
        raise RuntimeError("unexpected_default_fallback")
    if default_output() != "vrct.decoy.sink":
        raise RuntimeError("decoy_not_default")
    if not bus.close():
        raise RuntimeError("worker_not_released")
    return {"cancel": cancel, "disconnect_to_idle_ms": disconnect_ms,
            "disconnect_error": failed["last_error"], "missing_error": missing["last_error"],
            "recovered_after_explicit_reselect": True, "decoy_nonzero_chunks": 0,
            "decoy_confirmed_default": True}


def measure_tts(stack, url, samples, warmup, rows, reports):
    capture = Capture(stack, "vrct.test.source")
    quiet_since = time.monotonic_ns()
    wait_for(lambda: capture.quiet(quiet_since), code="pre_tts_not_silent")
    router = TimedRouter()
    bus = VoiceEventBus(VoiceSettings(mode="original", output_device="vrct.test.sink", japanese_url=url), router=router)
    stack.callback(bus.close)
    for index in range(warmup + samples):
        capture.reset()
        event = make_event(f"tts-{index}")
        bus.publish(event)
        status = wait_for(lambda: idle(bus), timeout=35)
        if status["errors"] or status["completed"] != index + 1:
            raise RuntimeError("tts_" + (status["last_error"] or "incomplete"))
        wait_for(lambda: capture.quiet(event.timestamp_ns))
        observation = capture.snapshot()
        if observation["first_nonzero_ns"] is None or router.first_write_ns is None:
            raise RuntimeError("tts_silent")
        warm = "warmup" if index < warmup else "yes"
        for metric, end in (("event_to_first_pcm_write", router.first_write_ns),
                            ("event_to_private_source_read", observation["first_nonzero_ns"])):
            rows.append({"metric": metric, "environment": "linux_private_pipewire", "warm": warm,
                         "start_ns": event.timestamp_ns, "end_ns": end})
        reports.append({"index": index, "warm": warm, "sample_rate": status["sample_rate"],
                        "nonzero_chunks": observation["nonzero_chunks"]})
        print(json.dumps({"sample": index + 1, "of": warmup + samples,
                          "first_write_ms": status["last_first_write_ms"]}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=local_url, help="Existing Japanese speech.cpp server; never started or downloaded")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--route-runs", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True, help="New report directory (must not exist)")
    args = parser.parse_args(argv)
    if not 1 <= args.samples <= 1000 or not 0 <= args.warmup <= 20 or not 1 <= args.route_runs <= 100:
        parser.error("samples must be 1..1000, warmup 0..20, route-runs 1..100")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema": 1, "os": platform.platform(), "python": platform.python_version(),
              "raw_audio_saved": False, "physical_microphone_captured": False,
              "graph": "private_pipewire_policy_only", "vrchat_verified": False,
              "ui_verified": False, "rows": [], "samples": [], "routing_trials": [], "status": "failed"}
    try:
        with private_graph() as stack:
            loopback(stack, "vrct.decoy")
            wait_for(default_output, code="default_metadata_not_ready")
            # A real alternative default must exist for the fallback test.
            subprocess.run(["pw-metadata", "-n", "default", "0", "default.configured.audio.sink",
                            '{"name":"vrct.decoy.sink"}', "Spa:String:JSON"],
                           check=True, capture_output=True, timeout=3)
            wait_for(lambda: default_output() == "vrct.decoy.sink", code="decoy_not_default")
            decoy = Capture(stack, "vrct.decoy.source")
            for index in range(args.route_runs):
                with ExitStack() as trial:
                    target = loopback(trial, "vrct.test")
                    capture = Capture(trial, "vrct.test.source")
                    result = exercise_routes(trial, capture, target, decoy)
                    report["routing_trials"].append(result)
                wait_for(lambda: "vrct.test.sink" not in nodes(), code="target_not_released")
            if args.server:
                # Exercise HTTP cancellation/recovery as well as synthetic routing.
                with ExitStack() as trial:
                    target = loopback(trial, "vrct.test")
                    capture = Capture(trial, "vrct.test.source")
                    report["tts_fault_smoke"] = exercise_routes(trial, capture, target, decoy, args.server)
                wait_for(lambda: "vrct.test.sink" not in nodes(), code="target_not_released")
                loopback(stack, "vrct.test")
                measure_tts(stack, args.server, args.samples, args.warmup, report["rows"], report["samples"])
            report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as exc:
        # Codes/classes only. Do not dump arbitrary server text or local paths.
        report["failure_type"] = type(exc).__name__
        if isinstance(exc, (RuntimeError, TimeoutError)):
            report["failure_code"] = str(exc)
    finally:
        report["summary"] = summarize(report["rows"])
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        with (args.output / "latency.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["metric", "environment", "warm", "start_ns", "end_ns"])
            writer.writeheader()
            writer.writerows(report["rows"])
    print(json.dumps({"status": report["status"], "summary": report["summary"],
                      "failure_code": report.get("failure_code")}), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
