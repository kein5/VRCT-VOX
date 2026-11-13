"""Raw PCM via pw-cat; explicit sink and bounded, cancellable pipe writes."""
import json
import fcntl
import os
import select
import subprocess
from runtime_paths import external_process_env
import time

from models.tts.speechcpp_tts import SpeechError


def _dump():
    result = subprocess.run(["pw-dump"], env=external_process_env(), capture_output=True, timeout=3, check=True)
    return json.loads(result.stdout)


def enumerate_outputs():
    try:
        nodes = _dump()
        return [{"id": n["info"]["props"]["node.name"],
                 "label": n["info"]["props"].get("node.description", n["info"]["props"]["node.name"])}
                for n in nodes if n.get("info", {}).get("props", {}).get("media.class") == "Audio/Sink"]
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as exc:
        raise SpeechError("pipewire_unavailable") from exc


def default_output():
    """The session's default sink name. Monitor only: TTS never uses a default."""
    try:
        nodes = _dump()
        for node in nodes:
            if (node.get("type") != "PipeWire:Interface:Metadata"
                    or node.get("props", {}).get("metadata.name") != "default"):
                continue
            entries = {e.get("key"): e.get("value") for e in node.get("metadata") or [] if e.get("subject") == 0}
            for key in ("default.audio.sink", "default.configured.audio.sink"):
                value = entries.get(key)
                value = json.loads(value) if isinstance(value, str) else value
                if isinstance(value, dict) and isinstance(value.get("name"), str) and value["name"]:
                    return value["name"]
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError) as exc:
        raise SpeechError("pipewire_unavailable") from exc
    raise SpeechError("output_missing")


class PipeWireOutput:
    def __init__(self, device, rate, channels, *, expected_identity=None, node_name="vrct.tts"):
        target = device
        if expected_identity is None:
            if device not in {d["id"] for d in enumerate_outputs()}:
                raise SpeechError("output_missing")
        else:
            from .source_bridge import _read_graph, _endpoint
            endpoint = _endpoint(_read_graph(), device, 'Audio/Sink')
            if (endpoint.cookie, endpoint.serial) != expected_identity:
                raise SpeechError('output_identity_changed')
            target = str(endpoint.serial)
        self.process = subprocess.Popen(
            ["pw-cat", "--playback", "--raw", "--format", "s16", "--rate", str(rate),
             "--channels", str(channels), "--latency", "20ms", "--target", target,
             "--properties", "{ node.name=" + node_name + " node.dont-fallback=true node.dont-reconnect=true node.dont-move=true }", "-"], env=external_process_env(),
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
                    token.check()
                    def write():
                        return os.write(self.process.stdin.fileno(), pending)
                    commit = getattr(token, 'commit_audio_write', None)
                    count = commit(pending, write) if commit is not None else write()
                    pending = pending[count:]
                except BlockingIOError:
                    continue
                except BrokenPipeError as exc:
                    raise SpeechError("output_disconnected") from exc

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
