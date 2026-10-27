"""Raw PCM via pw-cat; explicit sink and bounded, cancellable pipe writes."""
import json
import fcntl
import os
import select
import subprocess
import time

from models.tts.speechcpp_tts import SpeechError


def enumerate_outputs():
    try:
        result = subprocess.run(["pw-dump"], capture_output=True, timeout=3, check=True)
        nodes = json.loads(result.stdout)
        return [{"id": n["info"]["props"]["node.name"],
                 "label": n["info"]["props"].get("node.description", n["info"]["props"]["node.name"])}
                for n in nodes if n.get("info", {}).get("props", {}).get("media.class") == "Audio/Sink"]
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as exc:
        raise SpeechError("pipewire_unavailable") from exc


class PipeWireOutput:
    def __init__(self, device, rate, channels):
        if device not in {d["id"] for d in enumerate_outputs()}:
            raise SpeechError("output_missing")
        self.process = subprocess.Popen(
            ["pw-cat", "--playback", "--raw", "--format", "s16", "--rate", str(rate),
             "--channels", str(channels), "--latency", "20ms", "--target", device,
             "--properties", "{ node.name=vrct.tts node.dont-fallback=true node.dont-reconnect=true }", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, bufsize=0,
        )
        # Bound the kernel queue as well as the scheduler (about 85 ms at 24 kHz).
        try:
            fcntl.fcntl(self.process.stdin.fileno(), fcntl.F_SETPIPE_SZ, 4096)
            os.set_blocking(self.process.stdin.fileno(), False)
        except Exception:
            self.process.stdin.close()
            self.process.kill()
            self.process.wait(timeout=0.5)
            raise

    def write(self, pcm, token):
        deadline = time.monotonic() + 2
        pending = memoryview(pcm)
        while pending:
            token.check()
            if self.process.poll() is not None:
                raise SpeechError("output_disconnected")
            if time.monotonic() > deadline:
                raise SpeechError("output_stalled")
            _, writable, _ = select.select([], [self.process.stdin], [], 0.02)
            if writable:
                try:
                    count = os.write(self.process.stdin.fileno(), pending)
                    pending = pending[count:]
                except BlockingIOError:
                    continue

    def close(self, *, drain, token):
        try:
            self.process.stdin.close()
            deadline = time.monotonic() + (2 if drain else 0)
            while drain and not token.is_set() and time.monotonic() < deadline:
                if self.process.poll() is not None:
                    if self.process.returncode:
                        raise SpeechError("output_failed")
                    return
                token.wait(0.01)
            if drain and not token.is_set():
                raise SpeechError("output_drain_timeout")
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=0.5)
