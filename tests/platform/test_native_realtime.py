"""Actual Tauri/Model + speech.cpp + private PipeWire; HTTP translation fixture.

No host capture, model download, real MT-quality claim or VRChat connection.
"""

from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from queue import Empty, Queue
import socket
import subprocess
from threading import Event, Thread
import time
import wave

import pytest

from native_webdriver import NativeWebDriver
from test_native_ui import initial_state
from models.audio_routing.devices_pipewire import PipeWireOutput
from models.transcription.capture_pipewire import enumerate_endpoints
from models.transcription.realtime_settings import endpoint_dict, normalize_settings
from models.transcription.speechcpp_asr import ASRError, SpeechCppASR
from models.tts.speechcpp_tts import CancelToken
from tools.voice_acceptance import loopback, nodes, private_graph, stop_process, wait_for

pytestmark = pytest.mark.skipif(
    os.environ.get("VRCT_TEST_NATIVE_GUI") != "1" or not os.environ.get("VRCT_SPEECH_VAD_MODEL"),
    reason="consented ASR/VAD assets, native build and display guard required",
)


class TranslationFixture:
    """The production LMStudio provider talks to this deterministic HTTP peer."""

    def __init__(self, translations=None):
        self.translations = translations

    def __enter__(self):
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def respond(self, value):
                data = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                assert self.path == "/v1/models"
                self.respond({"data": [{"id": "caption-integration-fixture", "object": "model"}]})

            def do_POST(self):
                assert self.path == "/v1/chat/completions"
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert request["model"] == "caption-integration-fixture"
                owner.requests.append({"time_ns": time.monotonic_ns(), "message_count": len(request["messages"])})
                self.respond({"id": "fixture", "object": "chat.completion", "created": 0,
                              "model": request["model"], "choices": [{"index": 0, "finish_reason": "stop",
                              "message": {"role": "assistant", "content": (
                                  owner.translations[(len(owner.requests) - 1) % len(owner.translations)]
                                  if owner.translations else "Integration translation " + str(len(owner.requests)))}}]})

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=lambda: self.server.serve_forever(0.02), daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


class SyntheticProducer:
    def __init__(self, pcm):
        self.pcm, self.queue = pcm, Queue(maxsize=2)
        self.token, self.errors = CancelToken(), []

    def __enter__(self):
        output = PipeWireOutput("vrct.native.caption.sink", 48000, 1)

        def run():
            pending, finished = b"", None
            try:
                while not self.token.is_set():
                    if not pending:
                        if finished:
                            finished.set()
                            finished = None
                        try:
                            finished = self.queue.get_nowait()
                            pending = b"\0\0" * 24000 + self.pcm + b"\0\0" * 72000
                        except Empty:
                            pass
                    block, pending = pending[:1920], pending[1920:]
                    output.write(block.ljust(1920, b"\0"), self.token)
            except Exception as error:
                if not self.token.is_set():
                    self.errors.append(type(error).__name__)
            finally:
                output.close(drain=False, token=self.token)

        self.thread = Thread(target=run, daemon=True)
        self.thread.start()
        return self

    def play(self):
        finished = Event()
        self.queue.put_nowait(finished)
        return finished

    def __exit__(self, *args):
        self.token.cancel()
        self.thread.join(3)
        assert not self.thread.is_alive() and not self.errors, self.errors


def open_captions(ui):
    ui.wait("return innerWidth >= 500 && innerHeight >= 300")
    # This trial deliberately has no external network. Dismiss that expected
    # notification through its real close control before opening settings.
    notice = ui.evaluate("return [...document.querySelectorAll('.Toastify__toast')].find(e => e.textContent.startsWith('Network is not connected.'))?.querySelector('button svg')")
    if notice:
        ui.element_command(notice, "click")
    ui.click('[class*="open_config_page_button"]')
    ui.wait("return [...document.querySelectorAll('p')].some(e => e.textContent === 'Go Back' && getComputedStyle(e).visibility === 'visible')")
    if not ui.evaluate("return !!document.querySelector('section[aria-label=\"Realtime captions\"]')"):
        tab = ui.evaluate("return [...document.querySelectorAll('p')].find(e => e.textContent === 'Transcription')?.parentElement")
        ui.element_command(tab, "click")
    ui.wait("return !!document.querySelector('section[aria-label=\"Realtime captions\"] select')")


def instrument_rows(ui):
    ui.evaluate("""
        window.__captionRows = []; window.__captionSnapshots = [];
        const ids = new WeakMap(); let serial = 0;
        function sample() {
            const rows = [...document.querySelectorAll('#log_container > div')]
                .filter(e => e.querySelector('[class*=category]'));
            window.__captionRows = rows.map(e => {
                if (!ids.has(e)) ids.set(e, ++serial);
                return { node: ids.get(e), category: e.querySelector('[class*=category]').textContent,
                    translated: !!e.querySelector('[class*=message_second]'), characters: e.textContent.length };
            });
            window.__captionSnapshots.push({ms: performance.now(), rows: window.__captionRows});
            if (window.__captionSnapshots.length > 512) window.__captionSnapshots.shift();
        }
        window.__captionObserver = new MutationObserver(sample);
        window.__captionObserver.observe(document.querySelector('#log_container'), {childList:true,subtree:true,characterData:true});
        sample(); return true;
    """)


def test_real_asr_native_caption_translation_and_stop(tmp_path):
    binary = Path(os.environ["VRCT_SPEECH_BINARY"]).resolve(strict=True)
    models = [Path(os.environ[name]).resolve(strict=True) for name in ("VRCT_SPEECH_ASR_MODEL", "VRCT_SPEECH_VAD_MODEL")]
    with wave.open(os.environ["VRCT_SPEECH_ASR_INPUT"], "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
        pcm = wav.readframes(wav.getnframes())
    with private_graph(), ExitStack() as stack:
        loopback(stack, "vrct.native.caption")
        producer = stack.enter_context(SyntheticProducer(pcm))  # stable topology before capture
        translation = stack.enter_context(TranslationFixture())
        osc = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        osc.bind(("127.0.0.2", 0))
        osc.setblocking(False)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        log = stack.enter_context((tmp_path / "speech-server.log").open("wb"))
        server = subprocess.Popen([str(binary), "serve", *map(str, models), "--host", "127.0.0.1",
                                   "--port", str(port), "--device", "gpu"], stdout=log, stderr=log)
        stack.callback(stop_process, server)
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 20
        while True:
            assert server.poll() is None and time.monotonic() < deadline
            try:
                recognizers = SpeechCppASR(url, timeout=1).recognizers()
                break
            except ASRError:
                time.sleep(0.05)
        choices = normalize_settings({"base_url": url, "model": recognizers[0].id})
        for source in ("mic", "speaker"):
            choices[source]["endpoint"] = endpoint_dict(next(row["endpoint"] for row in enumerate_endpoints(source)
                if row["endpoint"].name == "vrct.native.caption." + ("source" if source == "mic" else "sink")))
        state_dir = initial_state(tmp_path)
        config_path = state_dir / "config.json"
        config = json.loads(config_path.read_text())
        languages = {str(tab): {str(slot): {"language": "English", "country": "United States", "enable": slot == 1}
                              for slot in range(1, 4)} for tab in range(1, 6)}
        targets = {str(tab): {str(slot): {"language": "German", "country": "Germany", "enable": slot == 1}
                             for slot in range(1, 4)} for tab in range(1, 6)}
        config.update(REALTIME_ASR_SETTINGS=choices, LMSTUDIO_URL=translation.url,
                      SELECTED_TRANSLATION_ENGINES={str(tab): "LMStudio" for tab in range(1, 6)},
                      SELECTED_YOUR_LANGUAGES=languages, SELECTED_TARGET_LANGUAGES=targets,
                      SEND_MESSAGE_TO_VRC=True, SEND_RECEIVED_MESSAGE_TO_VRC=True, OSC_PORT=osc.getsockname()[1])
        config_path.write_text(json.dumps(config))
        with NativeWebDriver(tmp_path / "first", {"VRCT_CONFIG_DIR": str(state_dir)}) as ui:
            ui.wait("return document.querySelector('textarea') !== null")
            ui.assert_rendered()
            # Use the production Translation toggle; no test-only backend hook.
            toggle = ui.evaluate("return [...document.querySelectorAll('[class*=switch_container]')].find(e => e.querySelector('p')?.textContent === 'Translation')")
            ui.element_command(toggle, "click")
            ui.wait("return [...document.querySelectorAll('[class*=switch_container]')].some(e => e.querySelector('p')?.textContent === 'Translation' && e.className.includes('is_active'))")
            open_captions(ui)
            ui.wait("return [...document.querySelectorAll('button')].some(e => e.textContent === 'Start microphone captions' && !e.disabled)")
            ui.click_text("button", "Start microphone captions")
            ui.click_text("button", "Start game audio captions")
            ui.wait("return [...document.querySelectorAll('[role=status]')].filter(e => e.textContent === 'Captions running').length === 2")
            ui.click_text("p", "Go Back")
            ui.wait("return !!document.querySelector('#log_container')")
            instrument_rows(ui)
            finished = producer.play()
            ui.wait("return window.__captionRows.length === 4 && window.__captionRows.every(e => e.translated)", timeout=15)
            assert finished.wait(3)
            rows = ui.evaluate("return window.__captionRows")
            snapshots = ui.evaluate("return window.__captionSnapshots")
            assert sorted(row["category"] for row in rows) == ["Received", "Received", "Sent", "Sent"]
            assert len(translation.requests) == 4
            assert any(not row["translated"] for snapshot in snapshots for row in snapshot["rows"])
            assert len({row["node"] for snapshot in snapshots for row in snapshot["rows"]}) == 4
            expected_osc = ui.evaluate("return [...document.querySelectorAll('#log_container > div')].filter(e => e.querySelector('[class*=category]')?.textContent === 'Sent').map(e => e.querySelector('[class*=message_main]').textContent)")
            from pythonosc.osc_packet import OscPacket
            messages = []
            while True:
                try:
                    messages.extend(t.message for t in OscPacket(osc.recv(65536)).messages)
                except BlockingIOError:
                    break
            sent = [message.params[0] for message in messages if message.address == "/chatbox/input"]
            assert len(sent) == len(expected_osc) == 2
            # Match each datagram to a microphone row, not merely the total;
            # a swapped or duplicated speaker final must fail this check.
            assert all(sum(translation in text for text in sent) == 1 for translation in expected_osc)
            # Main-view source controls stop capture without opening config,
            # whose existing lifecycle temporarily disables translation.
            ui.click_text("button", "Stop microphone captions")
            ui.click_text("button", "Stop game audio captions")
            wait_for(lambda: not any(name.startswith("vrct.asr.capture.") for name in nodes()))
            instrument_rows(ui)
            assert producer.play().wait(10)
            time.sleep(0.5)
            assert len(translation.requests) == 4
            assert ui.evaluate("return window.__captionRows") == rows
            ui.assert_rendered()
            ui.close_app()
        saved = json.loads(config_path.read_text())
        assert saved["REALTIME_ASR_SETTINGS"] == choices
        assert "/run/realtime_caption" not in (state_dir / "logs" / "process.log").read_text()
        with NativeWebDriver(tmp_path / "restart", {"VRCT_CONFIG_DIR": str(state_dir)}) as ui:
            ui.wait("return document.querySelector('textarea') !== null")
            open_captions(ui)
            ui.wait("return [...document.querySelectorAll('[role=status]')].filter(e => e.textContent === 'Captions stopped').length === 2")
            assert not any(name.startswith("vrct.asr.capture.") for name in nodes())
            ui.close_app()
        (tmp_path / "report.json").write_text(json.dumps({
            "actual_native_ui": True, "actual_speechcpp_vad": True, "private_os_capture": True,
            "physical_capture": False, "translation_engine": "production LMStudio HTTP adapter with deterministic fixture",
            "real_translation_model": False, "final_rows": rows, "ui_snapshots": snapshots,
            "translation_requests": len(translation.requests), "mic_osc_messages": 2, "speaker_osc_messages": 0,
            "osc_matched_microphone_translations": True, "captions_in_implicit_process_log": False,
            "stopped_input_replay_no_results": True, "restart_capture_off": True,
        }, indent=2) + "\n")
