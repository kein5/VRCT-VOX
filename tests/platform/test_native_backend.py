"""Opt-in real Model/Main startup over stdio; no controller or service stubs.

Run with VRCT_TEST_NATIVE=1 in the Linux runtime venv. This uses fresh settings,
disables telemetry/capture/OSC sending, and never opts in to model downloads.
It is separate from the model-free voice suite and does not test a Tauri window.
"""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("VRCT_TEST_NATIVE") != "1",
    reason="opt-in real Linux backend startup",
)


@contextmanager
def backend(state, attempt):
    env = dict(os.environ, VRCT_CONFIG_DIR=str(state),
               HF_HOME=str(state / "hf"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    events = Queue()
    with (state / f"stderr-{attempt}.log").open("w") as stderr, \
            (state / f"stdout-{attempt}.log").open("w") as stdout:
        process = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "src-python/mainloop.py")],
            cwd=state, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=stderr, text=True, encoding="utf-8",
        )

        def collect():
            for line in process.stdout:
                stdout.write(line)
                stdout.flush()
                try:
                    events.put(json.loads(line))
                except ValueError:
                    events.put({"unstructured": line})

        reader = Thread(target=collect, daemon=True)
        reader.start()

        def send(endpoint, data=None):
            payload = None if data is None else base64.b64encode(
                json.dumps(data, ensure_ascii=False).encode()).decode()
            process.stdin.write(json.dumps({"endpoint": endpoint, "data": payload}) + "\n")
            process.stdin.flush()

        def wait(endpoint, timeout=40):
            deadline = time.monotonic() + timeout
            next_feed = 0
            while time.monotonic() < deadline:
                assert process.poll() is None, f"backend exited; see {state}"
                if time.monotonic() >= next_feed:
                    send("/run/feed_watchdog")
                    next_feed = time.monotonic() + 5
                try:
                    event = events.get(timeout=0.2)
                except Empty:
                    continue
                if event.get("endpoint") == endpoint:
                    assert event["status"] == 200, event
                    return event.get("result")
            pytest.fail(f"timeout waiting for {endpoint}; see {state}")

        try:
            wait("/run/initialization_complete")
            # Consume the initial settings snapshot before making new requests.
            yield send, wait
            send("/run/shutdown")
            wait("/run/shutdown", timeout=20)
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            reader.join(timeout=2)
            process.stdin.close()
            process.stdout.close()


def test_real_startup_settings_and_restart_without_models(tmp_path):
    state = tmp_path / "native-state"
    state.mkdir()
    initial = {"AUTO_DOWNLOAD_MODELS": False, "ENABLE_TELEMETRY": False,
               "AUTO_MIC_SELECT": False, "AUTO_SPEAKER_SELECT": False,
               "SEND_MESSAGE_TO_VRC": False, "VRC_MIC_MUTE_SYNC": False,
               "OSC_IP_ADDRESS": "127.0.0.2", "WEBSOCKET_SERVER": False}
    (state / "config.json").write_text(json.dumps(initial))
    with backend(state, 1) as (send, wait):
        send("/get/data/auto_download_models")
        assert wait("/get/data/auto_download_models") is False
        send("/get/data/voice_settings")
        settings = wait("/get/data/voice_settings")
        assert settings["mode"] == "off"
        settings["japanese_voice"] = "保存テスト"
        send("/set/data/voice_settings", settings)
        assert wait("/set/data/voice_settings")["japanese_voice"] == "保存テスト"
    with backend(state, 2) as (send, wait):
        send("/get/data/voice_settings")
        restored = wait("/get/data/voice_settings")
        assert restored["japanese_voice"] == "保存テスト"
        assert restored["mode"] == "off"
    for attempt in (1, 2):
        log = (state / f"stdout-{attempt}.log").read_text()
        assert "End Initialization" in log
        assert "Download CTranslate2 Model Weight" not in log
        assert "Download Whisper Model Weight" not in log
