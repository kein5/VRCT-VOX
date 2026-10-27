"""Opt-in real Tauri + full backend + private PipeWire voice acceptance.

VRCT_TEST_NATIVE_VOICE=1 uses an HTTP PCM fixture. To test real inference, also
set VRCT_TEST_SPEECH_MODEL and VRCT_TEST_SPEECH_BINARY to existing local files.
No Tauri IPC, Model, Controller or audio output is replaced. No physical input
or VRChat is captured. All audio is the fixed test utterance or synthetic PCM.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from native_webdriver import NativeWebDriver, ROOT
from test_native_ui import initial_state

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("VRCT_TEST_NATIVE_VOICE") != "1",
    reason="requires opt-in native GUI, private PipeWire and an existing engine or PCM fixture",
)


def test_native_text_to_virtual_microphone_and_recovery(tmp_path):
    sys.path.insert(0, str(ROOT / "tests/voice"))
    from ui_entry_acceptance import FixtureServer
    from tools.live_tts_acceptance import SpeechServer, SHORT, LONG
    from tools.voice_acceptance import private_graph, wait_for
    from tools.voice_b_poc import ToneCapture, settled
    from tools.vrchat_gui_probe import Capture
    from tools.vrchat_audio_probe import compare_pcm
    from tools.managed_vrchat_probe import require_continuous_capture
    from models.audio_routing.pipewire_gate import PipeWireGate
    from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS

    model = os.environ.get("VRCT_TEST_SPEECH_MODEL")
    binary = os.environ.get("VRCT_TEST_SPEECH_BINARY")
    report = {"status": "failed", "native_tauri": True, "full_model_runtime": True,
              "real_inference": bool(model), "vrchat": False, "physical_input": False,
              "host_audio_changed": False, "cases": [],
              "timing_boundary": "WebDriver click call to first qualifying private source read",
              "latency_percentiles": None}
    try:
        with private_graph(config_fragment=ROOT / "config/pipewire/90-vrct-managed.conf"), ExitStack() as stack:
            gate = PipeWireGate()
            identity = gate.inspect()["identity"]
            capture = ToneCapture(stack, "vrct.managed.source")
            if model:
                assert binary and Path(model).is_file() and Path(binary).is_file()
                server = SpeechServer(SimpleNamespace(model=Path(model), output=tmp_path,
                                      speech_binary=binary, device="Vulkan0", seed=42))
                with Path(model).open("rb") as stream:
                    report["model_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                with Path(binary).open("rb") as stream:
                    report["binary_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                report["seed"] = 42
            else:
                server = FixtureServer()
            stack.callback(server.stop)
            server.start()

            def reference():
                frames = list(SpeechCppTTS(server.url).synthesize_stream(SHORT, "none", "ja", CancelToken()))
                assert frames and all(f.sample_rate == 48000 and f.channels == 1 for f in frames)
                return b"".join(frame.pcm for frame in frames)

            # Fixed server seed must produce the same PCM twice before using an
            # independently generated utterance as the exactly-once reference.
            pcm = reference()
            assert reference() == pcm, "reference_generation_not_deterministic"
            (tmp_path / "reference.pcm").write_bytes(pcm)
            report["reference_samples"] = len(pcm) // 2
            state = initial_state(tmp_path)
            with NativeWebDriver(tmp_path / "ui", {"VRCT_CONFIG_DIR": str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()

                def status(text):
                    ui.wait(f"return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === {json.dumps(text)})")

                def save(mode):
                    ui.select("Audio route", "managed")
                    ui.select("Read aloud", mode)
                    ui.fill("Japanese server (Irodori)", server.url)
                    ui.click_text("button", "Save voice settings")
                    wait_for(lambda: json.loads((state / "config.json").read_text()).get("VOICE_SETTINGS", {}).get("mode") == mode)

                def home():
                    ui.click_text("p", "Go Back")

                def send(text):
                    field = ui.command("POST", "/element", {"using": "css selector", "value": "textarea"})
                    ui.element_command(field, "clear")
                    ui.element_command(field, "value", {"text": text})
                    started = time.monotonic_ns()
                    ui.click('[class*="message_send_button"]')
                    ui.wait("return document.querySelector('textarea').value === ''")
                    return started

                def first_audio(start):
                    def observe():
                        with capture.lock:
                            return next((t for t, _, nonzero in capture.history if t >= start and nonzero), None)
                    return wait_for(observe, timeout=15, code="native_ui_no_audio")

                def done(name, **observations):
                    require_continuous_capture(capture.snapshot())
                    assert gate.inspect()["identity"] == identity
                    report["cases"].append({"name": name, "status": "passed", **observations})

                def positive(name):
                    settled(capture, time.monotonic_ns(), "before_send_not_silent", silent=True)
                    path = tmp_path / f"{name}.pcm"
                    recording = Capture("vrct.managed.source", path)
                    try:
                        time.sleep(.3)
                        start = send(SHORT)
                        first = first_audio(start)
                        wait_for(lambda: capture.settled(first, silent=True),
                                 timeout=len(pcm) / 96000 + 5, code="normal_completion_not_silent")
                    finally:
                        observation = recording.close()
                    assert observation["valid"], observation
                    matched = compare_pcm(pcm, path.read_bytes(), 48000)
                    assert matched["verdict"] == "pass" and matched["occurrences"] == 1, matched
                    done(name, click_to_source_ms=(first - start) / 1e6, match=matched, capture=observation)

                save("original")
                status("Muted (confirmed)")
                ui.click_text("button", "Resume voice")
                status("Voice enabled (confirmed)")
                home()
                positive("normal_exactly_once")

                for name, button in [("stop", "Stop playback and clear queue"), ("mute", "Mute until resumed")]:
                    start = send(LONG)
                    first_audio(start)
                    ui.open_voice_settings()
                    before = time.monotonic_ns()
                    ui.click_text("button", button)
                    silent = settled(capture, before, name + "_not_silent", silent=True)
                    elapsed = (silent - before) / 1e6
                    assert elapsed < 500, (name, elapsed)
                    done(name, click_to_silence_ms=elapsed, silence_confirmation_ms=2000)
                    home()

                start = send(SHORT)
                settled(capture, start, "held_mute_leaked_audio", silent=True)
                done("held_mute_stays_silent")
                ui.open_voice_settings()
                save("off")
                ui.click_text("button", "Resume voice")
                status("Voice enabled (confirmed)")
                home()
                start = send(SHORT)
                settled(capture, start, "off_leaked_audio", silent=True)
                done("off_keeps_text_silent")

                ui.open_voice_settings()
                save("original")
                home()
                positive("off_to_original_exactly_once")

                start = send(LONG)
                first_audio(start)
                crashed = time.monotonic_ns()
                server.stop(kill=True)
                silent = settled(capture, crashed, "server_failure_not_silent", silent=True)
                assert (silent - crashed) / 1e6 < 500
                ui.open_voice_settings()
                ui.wait("return [...document.querySelectorAll('[role=alert]')].some(e => /server_unavailable|transport_error/.test(e.textContent))")
                done("server_failure_visible_and_silent", crash_to_silence_ms=(silent - crashed) / 1e6)
                home()
                start = send(SHORT)
                settled(capture, start, "absent_server_leaked_audio", silent=True)
                server.start()
                settled(capture, time.monotonic_ns(), "server_restart_replayed_stale_audio", silent=True)
                positive("fresh_after_server_restart")
                ui.assert_rendered()
                ui.close_app()
            assert gate.inspect()["muted"] is True
            settled(capture, time.monotonic_ns(), "app_exit_not_silent", silent=True)
            done("app_exit_mutes_source")
            report["capture"] = capture.snapshot()
            report["status"] = "passed"
    finally:
        (tmp_path / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
