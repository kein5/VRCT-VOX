"""Actual native UI: OSC sender and calibrated first-write evidence, opt-in.

Only the fixed Japanese test sentence is synthesized. Private PipeWire means
no physical microphone/host output/VRChat capture. UDP receipt is NOT evidence
that VRChat rendered the Chatbox. No IPC or application handler is replaced.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys
import time
from types import SimpleNamespace

import pytest

from native_webdriver import NativeWebDriver, ROOT
from native_voice_measurement import calibrate, elapsed_bounds, summarize_trials, exact_pcm
from test_native_ui import initial_state

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("VRCT_TEST_NATIVE_MEASUREMENT") != "1",
    reason="requires opt-in native GUI, private PipeWire and a local engine or PCM fixture",
)


def test_native_osc_once_with_voice_and_ui_to_write_measurement(tmp_path):
    sys.path.insert(0, str(ROOT / "tests/voice"))
    from ui_entry_acceptance import FixtureServer
    from pythonosc.osc_packet import OscPacket
    from models.audio_routing.pipewire_gate import PipeWireGate
    from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS
    from tools.live_tts_acceptance import SpeechServer, SHORT
    from tools.managed_vrchat_probe import require_continuous_capture
    from tools.voice_acceptance import private_graph, wait_for
    from tools.voice_b_poc import ToneCapture, settled
    from tools.vrchat_gui_probe import Capture
    from tools.vrchat_audio_probe import compare_pcm, silence_pcm

    model = os.environ.get("VRCT_TEST_SPEECH_MODEL")
    binary = os.environ.get("VRCT_TEST_SPEECH_BINARY")
    managed_server = os.environ.get('VRCT_TEST_MEASUREMENT_MANAGED') == '1'
    low_latency = os.environ.get('VRCT_TEST_MEASUREMENT_LOW_LATENCY') == '1'
    count = int(os.environ.get("VRCT_TEST_MEASUREMENT_TRIALS", "30" if model else "2"))
    assert 1 <= count <= 100
    report = {"status": "failed", "real_inference": bool(model), "native_tauri": True,
              "vrchat_display": False, "host_audio_changed": False, "trials": [],
              "timer_padding_ms": 1, "clock_assumption": "steady monotonic clocks, no suspend",
              "system": platform.platform(), "python": platform.python_version()}
    report.update(managed_server=managed_server, low_latency=low_latency)
    try:
        with private_graph(config_fragment=ROOT / "config/pipewire/90-vrct-managed.conf"), ExitStack() as stack:
            gate = PipeWireGate()
            identity = gate.inspect()["identity"]
            monitor = ToneCapture(stack, "vrct.managed.source")
            udp = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            udp.bind(("127.0.0.2", 0))
            udp.setblocking(False)
            if model:
                assert binary and Path(model).is_file() and Path(binary).is_file()
                server = SpeechServer(SimpleNamespace(model=Path(model), output=tmp_path,
                                      speech_binary=binary, device="Vulkan0", seed=42))
                for name, path in (("model", model), ("binary", binary)):
                    with Path(path).open("rb") as stream:
                        report[name + "_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                report["seed"] = 42
            else:
                server = FixtureServer()
            stack.callback(server.stop)
            server.start()

            def reference():
                frames = list(SpeechCppTTS(server.url).synthesize_stream(SHORT, "none", "ja", CancelToken()))
                assert frames and all(f.sample_rate == 48000 and f.channels == 1 for f in frames)
                return b"".join(f.pcm for f in frames)

            pcm = reference()
            assert pcm == reference(), "independent reference is not deterministic"
            (tmp_path / "reference.pcm").write_bytes(pcm)
            if managed_server:
                assert model
                server.stop()
            state = initial_state(tmp_path)
            config = json.loads((state / "config.json").read_text())
            config.update(SEND_MESSAGE_TO_VRC=True, OSC_PORT=udp.getsockname()[1], ENABLE_TRANSLATION=False)
            if managed_server:
                from models.speech_server.settings import normalize_settings
                config['SPEECH_SERVER_SETTINGS'] = normalize_settings({'profiles': {'japanese': {
                    'model': str(Path(model).resolve()), 'device': 'gpu', 'low_latency': low_latency}}})
                config.setdefault('VOICE_SETTINGS', {})['japanese_seed'] = '42'
            (state / "config.json").write_text(json.dumps(config))
            trace = tmp_path / "first-write.jsonl"

            def records():
                return [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []

            def packets():
                result = []
                while True:
                    try:
                        data, _ = udp.recvfrom(65536)
                    except BlockingIOError:
                        return result
                    for item in OscPacket(data).messages:
                        result.append({"address": item.message.address, "params": list(item.message.params)})

            with NativeWebDriver(tmp_path / "ui", {"VRCT_CONFIG_DIR": str(state),
                                                   "VRCT_VOICE_TRACE": str(trace)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_route_settings()
                ui.select('Audio route', 'managed')
                ui.click_text('button', 'Save audio route')
                wait_for(lambda: json.loads((state / 'config.json').read_text()).get('VOICE_SETTINGS', {}).get('routing') == 'managed')
                ui.click_text('button', 'Resume voice')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Voice enabled (confirmed)')")
                ui.close_settings()
                ui.open_voice_settings()
                if managed_server:
                    ui.click_text('button', 'Start server')
                    ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Ready')", timeout=120)
                    if low_latency:
                        ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Low-latency standby active')", timeout=15)

                def save(mode):
                    ui.select("Chat voice", mode)
                    if managed_server:
                        ui.select('Japanese server', 'bundled')
                    else:
                        ui.fill("Japanese server (Irodori)", server.url)
                    ui.click_text("button", "Save voice settings")
                    wait_for(lambda: json.loads((state / "config.json").read_text()).get("VOICE_SETTINGS", {}).get("mode") == mode)

                save("original")
                ui.close_settings()
                ui.click('[role=switch][aria-label=TTS]')
                ui.wait("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked')==='true'")
                ui.evaluate("""
                    window.__voiceMeasurements = [];
                    document.addEventListener('click', event => {
                        if (event.target.closest('[class*="message_send_button"]'))
                            window.__voiceMeasurements.push({ms: performance.now(), trusted: event.isTrusted});
                    }, {capture: true, passive: true});
                    return true;
                """)

                def trial(name, *, off=False):
                    row = {"name": name, "valid": False, "warm": name != "warmup"}
                    report["trials"].append(row)
                    settled(monitor, time.monotonic_ns(), "before_send_not_silent", silent=True)
                    # Check late duplicates from the previous trial instead of discarding them.
                    pending = packets()
                    assert not any(p["address"] == "/chatbox/input" for p in pending), pending
                    field = ui.evaluate("return [...document.querySelectorAll('textarea')].find(e => getComputedStyle(e).visibility === 'visible' && e.getClientRects().length)")
                    ui.element_command(field, "clear")
                    ui.element_command(field, "value", {"text": SHORT})
                    previous_trace = records()
                    previous_marks = ui.evaluate("return window.__voiceMeasurements.length")
                    recording = Capture("vrct.managed.source", tmp_path / f"{name}.pcm")
                    try:
                        time.sleep(.25)
                        before = calibrate(ui)
                        call_ns = time.monotonic_ns()
                        ui.click('[class*="message_send_button"]')
                        ui.wait("return [...document.querySelectorAll('textarea')].filter(e => getComputedStyle(e).visibility === 'visible' && e.getClientRects().length).every(e => e.value === '')")
                        if off:
                            settled(monitor, call_ns, "off_leaked_audio", silent=True)
                        else:
                            wait_for(lambda: len(records()) > len(previous_trace), timeout=20, code="first_write_trace_missing")
                            settled(monitor, time.monotonic_ns(), "completion_not_silent", silent=True)
                        after = calibrate(ui)
                    finally:
                        row["capture"] = recording.close()
                    marks = ui.evaluate("return window.__voiceMeasurements.slice(arguments[0])", previous_marks)
                    assert len(marks) == 1 and marks[0]["trusted"], marks
                    row.update(ui_event=marks[0], calibration=before + after, osc=packets())
                    messages = [p for p in row["osc"] if p["address"] == "/chatbox/input"]
                    assert len(messages) == 1 and messages[0]["params"] == [SHORT, True, True], messages
                    assert all(p["address"] in ("/chatbox/input", "/chatbox/typing") for p in row["osc"])
                    assert row["capture"]["valid"], row["capture"]
                    observed = (tmp_path / f"{name}.pcm").read_bytes()
                    new_records = records()[len(previous_trace):]
                    if off:
                        assert new_records == [], new_records
                        row["silence"] = silence_pcm(observed, 48000)
                        assert row["silence"]["verdict"] == "pass", row["silence"]
                    else:
                        assert len(new_records) == 1, new_records
                        row["trace"] = new_records[0]
                        assert row["trace"]["outcome"] == "completed" and row["trace"]["event_id"]
                        assert row["trace"]["sample_rate"] == 48000
                        row["outcome"] = row["trace"]["outcome"]
                        row.update(elapsed_bounds(row["trace"]["first_write_ns"], marks[0]["ms"], before + after))
                        row["match"] = compare_pcm(pcm, observed, 48000)
                        assert row["match"]["verdict"] == "pass" and row["match"]["occurrences"] == 1, row["match"]
                        row['exact_pcm'] = exact_pcm(pcm, observed)
                        assert row['exact_pcm']['valid'], row['exact_pcm']
                    assert gate.inspect()["identity"] == identity
                    require_continuous_capture(monitor.snapshot())
                    if low_latency:
                        row['low_latency_active'] = ui.evaluate("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Low-latency standby active')")
                        assert row['low_latency_active'], 'standby ended during measurement'
                    row["valid"] = True
                    (tmp_path / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    return row

                trial("warmup")
                for i in range(count):
                    trial(f"warm-{i:03d}")
                ui.open_voice_settings()
                save("off")
                ui.close_settings()
                trial("off", off=True)
                assert len({r["event_id"] for r in records()}) == count + 1
                ui.close_app()
            assert gate.inspect()["muted"] is True
            report["capture"] = monitor.snapshot()
            report["summary"] = summarize_trials([r for r in report["trials"] if r["name"].startswith("warm-")], real_inference=bool(model),
                target_p95_ms=float(os.environ.get('VRCT_TEST_MEASUREMENT_P95_MS', '800')))
            assert report["summary"]["verdict"] != "invalid_measurement", report["summary"]
        report["status"] = "passed"
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        (tmp_path / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
