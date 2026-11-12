"""Opt-in same native send -> own VRChat bubble and managed source evidence.

Requires a prepared private instance, isolated playback and managed input, and
either Show Own Chatbox / Forward or a second client to look from
(VRCT_TEST_VRCHAT_VIEW_WINDOW / _PID). Does not select devices, unmute game voice or
download weights. OCR proves only the ASCII marker, not Japanese accuracy.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from native_chatbox import OscForwarder, compare_source_pcm, marker_visible
from native_webdriver import NativeWebDriver
from test_native_ui import initial_state

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("VRCT_TEST_NATIVE_CHATBOX") != "1",
    reason="requires prepared private host VRChat instance, managed route and DPMS guard",
)


def test_native_same_send_chatbox_and_voice_then_off(tmp_path):
    from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
    from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS
    from tools.display_power_guard import check_displays_on
    from tools.live_tts_acceptance import SpeechServer, SHORT
    from tools.managed_vrchat_probe import require_continuous_capture
    from tools.voice_acceptance import wait_for
    from tools.voice_b_poc import ToneCapture, settled
    from tools.vrchat_audio_probe import compare_pcm, silence_pcm
    from tools.vrchat_gui_probe import Capture, command, verify_route

    settings = {key: os.environ["VRCT_TEST_" + key] for key in (
        "VRCHAT_WINDOW", "VRCHAT_PID", "REPLAY_SINK", "SPEECH_BINARY", "SPEECH_MODEL",
    )}
    # Where the bubble is looked for. The client itself shows its own bubble only with
    # Show Own Chatbox / Forward; a second client in the same instance (VIEW_*) always
    # sees it, and that is what another player sees.
    window = os.environ.get("VRCT_TEST_VRCHAT_VIEW_WINDOW", settings["VRCHAT_WINDOW"])
    window_pid = os.environ.get("VRCT_TEST_VRCHAT_VIEW_PID", settings["VRCHAT_PID"])
    report = {"status": "failed", "native_tauri": True, "real_inference": True,
              "vrchat_display": True, "vrchat_local_replay": False, "physical_hearing": False,
              "remote_player": False, "physical_input": False, "cases": [],
              "ocr_scope": "ASCII marker only", "latency_percentiles": None, "seed": 42}

    def activate(target, pid):
        check_displays_on()
        assert command("kdotool", "getwindowpid", target) == str(pid)
        command("kdotool", "windowactivate", target)
        wait_for(lambda: command("kdotool", "getactivewindow") == target, timeout=3)

    def screenshot(label):
        activate(window, window_pid)
        time.sleep(.3)
        path = tmp_path / (label + ".png")
        subprocess.run(["spectacle", "-a", "-b", "-n", "-e", "-S", "-o", str(path)], check=True, timeout=10)
        assert command("kdotool", "getactivewindow") == window
        assert command("kdotool", "getwindowpid", window) == window_pid
        assert struct.unpack(">II", path.read_bytes()[16:24]) == (1600, 900)
        text = command("tesseract", str(path), "stdout", "-l", "eng", "--psm", "11")
        path.with_suffix(".txt").write_text(text)
        check_displays_on()
        return {"image": path.name, "ocr": text}

    trace = tmp_path / "voice-trace.jsonl"

    def records():
        return [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []

    try:
        report["route_before"] = verify_route(SOURCE, settings["REPLAY_SINK"])
        gate = PipeWireGate()
        identity = gate.inspect()["identity"]
        assert gate.inspect()["muted"] is True
        with ExitStack() as stack:
            monitor = ToneCapture(stack, SOURCE)
            # VRChat's OSC input: 9000 unless the client was started with another port.
            relay = stack.enter_context(OscForwarder(("127.0.0.1", int(os.environ.get("VRCT_TEST_VRCHAT_OSC_PORT", "9000")))))
            server = SpeechServer(SimpleNamespace(model=Path(settings["SPEECH_MODEL"]), output=tmp_path,
                                  speech_binary=settings["SPEECH_BINARY"], device="Vulkan0", seed=42))
            stack.callback(server.stop)
            server.start()
            for key in ("SPEECH_MODEL", "SPEECH_BINARY"):
                with Path(settings[key]).open("rb") as stream:
                    report[key.lower() + "_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            spoken = SHORT + " VRCTCHECKA"

            def reference():
                frames = list(SpeechCppTTS(server.url).synthesize_stream(spoken, "none", "ja", CancelToken()))
                assert frames and all(f.sample_rate == 48000 and f.channels == 1 for f in frames)
                return b"".join(f.pcm for f in frames)

            pcm = reference()
            assert pcm == reference(), "reference_generation_not_deterministic"
            (tmp_path / "reference.pcm").write_bytes(pcm)
            state = initial_state(tmp_path)
            config = json.loads((state / "config.json").read_text())
            config.update(SEND_MESSAGE_TO_VRC=True, OSC_PORT=relay.port, ENABLE_TRANSLATION=False)
            (state / "config.json").write_text(json.dumps(config))
            with NativeWebDriver(tmp_path / "ui", {"VRCT_CONFIG_DIR": str(state), "VRCT_VOICE_TRACE": str(trace)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                windows = command("kdotool", "search", "--all", "--pid", str(ui.app_process.pid), "--title", "^VRCT-VOX$").splitlines()
                assert len(windows) == 1

                def native():
                    activate(windows[0], ui.app_process.pid)

                def saved(key):
                    return json.loads((state / "config.json").read_text()).get("VOICE_SETTINGS", {}).get(key)

                def save(mode):
                    # The route is on the Device page, the voice on the TTS page.
                    native()
                    ui.open_route_settings()
                    if ui.evaluate("return arguments[0].value", ui.control("Audio route")) != "managed":
                        ui.select("Audio route", "managed")
                        ui.click_text("button", "Save changes")
                        wait_for(lambda: saved("routing") == "managed")
                    ui.open_voice_settings()
                    ui.select("Chat voice", mode)
                    ui.fill("Japanese server (Irodori)", server.url)
                    ui.click_text("button", "Save changes")
                    wait_for(lambda: saved("mode") == mode)

                save("original")
                ui.open_route_settings()
                ui.click_text("button", "Resume voice")
                ui.wait("return [...document.querySelectorAll('[role=status], [role=status] p')].some(e => e.textContent === 'Voice enabled (confirmed)')")
                ui.close_settings()
                # Text is spoken only while the main TTS switch is on.
                ui.set_switch("TTS")

                for mode, marker in (("original", "VRCTCHECKA"), ("off", "VRCTCHECKW")):
                    row = {"mode": mode, "marker": marker, "status": "failed"}
                    report["cases"].append(row)
                    if mode == "off":
                        save("off")
                        ui.close_settings()
                    row["before"] = screenshot(mode + "-before")
                    assert marker not in row["before"]["ocr"], "stale_marker_before_send"
                    settled(monitor, time.monotonic_ns(), "before_send_not_silent", silent=True)
                    native()
                    field = ui.command("POST", "/element", {"using": "css selector", "value": "textarea[class*=message_box_input_area]"})
                    ui.element_command(field, "clear")
                    ui.element_command(field, "value", {"text": SHORT + " " + marker})
                    previous_trace = len(records())
                    previous_messages = len(relay.messages)
                    capture = Capture(SOURCE, tmp_path / (mode + ".pcm"))
                    try:
                        time.sleep(.3)
                        started = time.monotonic_ns()
                        ui.click('[class*="message_send_button"]')
                        ui.wait("return document.querySelector('textarea[class*=message_box_input_area]').value === ''")
                        if mode == "original":
                            wait_for(lambda: len(records()) > previous_trace, timeout=30, code="voice_trace_missing")
                        else:
                            time.sleep(5)
                        settled(monitor, started, "send_not_silent_after_completion", silent=True)
                        row["screenshots"] = []
                        for index in range(6):  # seen from a second client, the speaker may be turned away for a moment
                            observed = screenshot(f"{mode}-after-{index}")
                            row["screenshots"].append(observed)
                            if marker_visible(observed["ocr"], marker):
                                break
                        assert marker_visible(observed["ocr"], marker), "new_marker_not_rendered_once"
                    finally:
                        row["capture"] = capture.close()
                    assert row["capture"]["valid"], row["capture"]
                    row["osc"] = relay.messages[previous_messages:]
                    sent = [m for m in row["osc"] if m["address"] == "/chatbox/input"]
                    assert sent == [{"address": "/chatbox/input", "params": [SHORT + " " + marker, True, True]}], sent
                    assert relay.errors == [], relay.errors
                    row["traces"] = records()[previous_trace:]
                    observed_pcm = (tmp_path / (mode + ".pcm")).read_bytes()
                    if mode == "off":
                        assert row["traces"] == []
                        row["audio"] = silence_pcm(observed_pcm, 48000)
                    else:
                        assert len(row["traces"]) == 1 and row["traces"][0]["outcome"] == "completed"
                        row["audio"] = compare_pcm(pcm, observed_pcm, 48000)
                        assert row["audio"]["occurrences"] == 1
                        row["source_exact"] = compare_source_pcm(pcm, observed_pcm, 48000)
                        assert row["source_exact"]["verdict"] == "pass", row["source_exact"]
                    assert row["audio"]["verdict"] == "pass", row["audio"]
                    assert gate.inspect()["identity"] == identity
                    assert verify_route(SOURCE, settings["REPLAY_SINK"]) == report["route_before"]
                    require_continuous_capture(monitor.snapshot())
                    row["status"] = "passed"
                    print(mode + ": passed", flush=True)
                assert len([m for m in relay.messages if m["address"] == "/chatbox/input"]) == 2
                native()
                ui.close_app()
            assert gate.inspect()["muted"] is True
            settled(monitor, time.monotonic_ns(), "exit_not_silent", silent=True)
            require_continuous_capture(monitor.snapshot())
            report["capture"] = monitor.snapshot()
            report["status"] = "passed"
    finally:
        (tmp_path / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
