"""Opt-in full native UI -> existing speech.cpp -> prepared VRChat mic test.

Requires an isolated playback sink, managed source, calibrated Japanese desktop
Audio & Voice page, dedicated ydotoold and display-power guard. Does not install
routes, select hardware, launch VRChat or download models. Only fixed generated
speech is captured. Windows, physical hearing and remote players are not tested.
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

from native_webdriver import NativeWebDriver
from test_native_ui import initial_state


pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("VRCT_TEST_NATIVE_VRCHAT") != "1",
    reason="requires explicitly prepared host VRChat UI and isolated audio route",
)


def test_native_voice_through_vrchat_local_replay(tmp_path):
    from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
    from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS
    from tools.display_power_guard import check_displays_on
    from tools.live_tts_acceptance import SpeechServer, SHORT, LONG, captures
    from tools.managed_vrchat_probe import require_continuous_capture
    from tools.voice_acceptance import wait_for
    from tools.voice_b_poc import ToneCapture, settled
    from tools.vrchat_audio_probe import compare_pcm, silence_pcm
    from tools.vrchat_gui_probe import GUI, command, verify_route

    settings = {key: os.environ["VRCT_TEST_" + key] for key in (
        "VRCHAT_WINDOW", "VRCHAT_PID", "YDOTOOL_SOCKET", "READY_IMAGE",
        "RECORDING_IMAGE", "REPLAY_SINK", "SPEECH_BINARY", "SPEECH_MODEL",
    )}
    window, replay = settings["VRCHAT_WINDOW"], settings["REPLAY_SINK"]
    assert command("kdotool", "getwindowpid", window) == settings["VRCHAT_PID"]
    assert Path(settings["SPEECH_MODEL"]).is_file()
    assert Path(settings["SPEECH_BINARY"]).is_file()
    report = {"status": "failed", "native_tauri": True, "full_model_runtime": True,
              "real_inference": True, "vrchat_local_replay": True, "physical_input": False,
              "physical_hearing": False, "remote_player": False, "seed": 42, "cases": [],
              "timing_boundary": "WebDriver send/stop call to host source read",
              "latency_percentiles": None}
    try:
        check_displays_on()
        report["route_before"] = verify_route(SOURCE, replay)
        gate = PipeWireGate()
        identity = gate.inspect()["identity"]
        assert gate.inspect()["muted"] is True, "expected_initial_managed_mute"
        gui = GUI(window, settings["YDOTOOL_SOCKET"], tmp_path,
                  Path(settings["READY_IMAGE"]), Path(settings["RECORDING_IMAGE"]))

        def activate(target, pid):
            assert command("kdotool", "getwindowpid", target) == str(pid)
            command("kdotool", "windowactivate", target)
            wait_for(lambda: command("kdotool", "getactivewindow") == target,
                     timeout=3, code="window_focus_not_confirmed")

        with ExitStack() as stack:
            capture = ToneCapture(stack, SOURCE)
            server = SpeechServer(SimpleNamespace(
                model=Path(settings["SPEECH_MODEL"]), output=tmp_path,
                speech_binary=settings["SPEECH_BINARY"], device="Vulkan0", seed=42,
            ))
            stack.callback(server.stop)
            server.start()
            report["server_runs"] = server.runs
            for key in ("SPEECH_MODEL", "SPEECH_BINARY"):
                with Path(settings[key]).open("rb") as stream:
                    report[key.lower() + "_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()

            def reference():
                frames = list(SpeechCppTTS(server.url).synthesize_stream(SHORT, "none", "ja", CancelToken()))
                assert frames and all(f.sample_rate == 48000 and f.channels == 1 for f in frames)
                return b"".join(f.pcm for f in frames)

            pcm = reference()
            assert reference() == pcm, "reference_generation_not_deterministic"
            (tmp_path / "reference.pcm").write_bytes(pcm)
            report["reference_samples"] = len(pcm) // 2
            state = initial_state(tmp_path)
            with NativeWebDriver(tmp_path / "ui", {"VRCT_CONFIG_DIR": str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                # kdotool search defaults to OR, including an empty title regex.
                # A debug app can also own inspector/VR panel windows. Select
                # the configured main title AND PID; verify PID before actions.
                candidates = command("kdotool", "search", "--all", "--pid",
                                     str(ui.app_process.pid), "--title", "^VRCT$").splitlines()
                assert len(candidates) == 1, "ambiguous_owned_tauri_window"
                native_window = candidates[0]

                def native():
                    activate(native_window, ui.app_process.pid)

                def voice_settings():
                    native()
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
                    ui.close_settings()

                def send(text):
                    native()
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
                    check_displays_on()
                    require_continuous_capture(capture.snapshot())
                    assert gate.inspect()["identity"] == identity
                    assert verify_route(SOURCE, replay) == report["route_before"]
                    report["cases"].append({"name": name, "status": "passed", **observations})
                    print(name + ": passed", flush=True)

                def replay_case(name, silent=False):
                    settled(capture, time.monotonic_ns(), "before_send_not_silent", silent=True)
                    output = tmp_path / name
                    output.mkdir()
                    gui.output = output
                    activate(window, settings["VRCHAT_PID"])
                    gui.wait_state("ready", 6)
                    with captures(output, replay) as recorded:
                        began = time.monotonic()
                        time.sleep(.5)
                        gui.click(.715, .631)
                        gui.wait_state("recording", 5)
                        time.sleep(1.5)
                        start = send(SHORT)
                        activate(window, settings["VRCHAT_PID"])
                        if silent:
                            settled(capture, start, "silent_mode_leaked_audio", silent=True)
                            first = None
                        else:
                            first = first_audio(start)
                            wait_for(lambda: capture.settled(first, silent=True),
                                     timeout=len(pcm) / 96000 + 5, code="normal_completion_not_silent")
                        gui.wait_state("ready", 20)
                        time.sleep(max(0, 24 - (time.monotonic() - began)))
                    assert all(c["valid"] for c in recorded.values()), recorded
                    audio = {key: compare_pcm(pcm, (output / f"{key}.pcm").read_bytes(), 48000)
                             for key in recorded}
                    if silent:
                        assert all(a["occurrences"] == 0 for a in audio.values()), audio
                        assert silence_pcm((output / "mic.pcm").read_bytes(), 48000)["verdict"] == "pass"
                    else:
                        assert all(a["verdict"] == "pass" and a["occurrences"] == 1 for a in audio.values()), audio
                    done(name, captures=recorded, audio=audio,
                         click_to_source_ms=None if first is None else (first - start) / 1e6)

                voice_settings()
                save("original")
                status("Muted (confirmed)")
                ui.click_text("button", "Resume voice")
                status("Voice enabled (confirmed)")
                home()
                replay_case("normal_exactly_once")

                for name, button in [("stop", "Stop playback and clear queue"), ("mute", "Mute until resumed")]:
                    start = send(LONG)
                    first_audio(start)
                    voice_settings()
                    before = time.monotonic_ns()
                    ui.click_text("button", button)
                    quiet = settled(capture, before, name + "_not_silent", silent=True)
                    elapsed = (quiet - before) / 1e6
                    assert elapsed < 500, (name, elapsed)
                    done(name, click_to_silence_ms=elapsed, observation="host_source_only")
                    home()

                replay_case("held_mute_stays_silent", silent=True)
                voice_settings()
                save("off")
                ui.click_text("button", "Resume voice")
                status("Voice enabled (confirmed)")
                home()
                replay_case("off_keeps_text_silent", silent=True)

                voice_settings()
                save("original")
                home()
                replay_case("off_to_original_exactly_once")

                start = send(LONG)
                first_audio(start)
                crashed = time.monotonic_ns()
                server.stop(kill=True)
                quiet = settled(capture, crashed, "server_failure_not_silent", silent=True)
                assert (quiet - crashed) / 1e6 < 500
                voice_settings()
                ui.wait("return [...document.querySelectorAll('[role=alert]')].some(e => /server_unavailable|transport_error/.test(e.textContent))")
                done("server_failure_visible_and_silent", crash_to_silence_ms=(quiet - crashed) / 1e6,
                     observation="host_source_only")
                home()
                start = send(SHORT)
                settled(capture, start, "absent_server_leaked_audio", silent=True)
                server.start()
                settled(capture, time.monotonic_ns(), "server_restart_replayed_stale_audio", silent=True)
                replay_case("fresh_after_server_restart")
                native()
                ui.assert_rendered()
                ui.close_app()
            assert gate.inspect()["muted"] is True
            settled(capture, time.monotonic_ns(), "app_exit_not_silent", silent=True)
            done("app_exit_mutes_source", observation="host_source_only")
            report["capture"] = capture.snapshot()
            report["status"] = "passed"
    finally:
        if "gui" in locals():
            report["gui_observations"] = gui.observations
        (tmp_path / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
