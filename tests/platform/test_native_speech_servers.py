"""Real bundled servers, native GUI and private synthetic PipeWire endpoints."""
from contextlib import ExitStack
import http.client
import json
import os
from pathlib import Path
import sys
import time
import wave

import pytest

from native_webdriver import NativeWebDriver, ROOT
from test_native_realtime import SyntheticProducer, open_captions, instrument_rows
from test_native_spoken_translation import open_voice
from test_native_ui import initial_state
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
from models.speech_server.runtime import bundled_binary
from models.transcription.capture_pipewire import enumerate_endpoints
from tools.voice_acceptance import private_graph, loopback, nodes, wait_for
from tools.voice_b_poc import ToneCapture, settled

pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_OWNED_SPEECH') != '1', reason='opt-in native GUI and consented Qwen/ASR/VAD assets')


def control(ui, profile, label):
    return ui.evaluate("return [...document.querySelectorAll('fieldset')].find(e => e.querySelector('legend')?.textContent === arguments[0]) && [...[...document.querySelectorAll('fieldset')].find(e => e.querySelector('legend')?.textContent === arguments[0]).querySelectorAll('label')].find(e => e.firstChild.textContent.trim() === arguments[1])?.querySelector('input,select');", profile, label)


def fill(ui, profile, label, value):
    element = control(ui, profile, label)
    ui.element_command(element, 'clear')
    ui.element_command(element, 'value', {'text': str(value)})


def button(ui, profile, text):
    # The settings page is visible before its async server-settings form mounts.
    # Wait for this real control; do not bypass WebDriver hit testing or retry a
    # successful Start/Stop click.
    ui.wait("return [...document.querySelectorAll('fieldset')].some(e => e.querySelector('legend')?.textContent === " + json.dumps(profile) + ");")
    element = ui.evaluate("return [...[...document.querySelectorAll('fieldset')].find(e => e.querySelector('legend')?.textContent === arguments[0]).querySelectorAll('button')].find(e => e.textContent === arguments[1]);", profile, text)
    return ui.element_command(element, 'click')


def server_state(ui, profile, expected, timeout=125):
    return ui.wait("return [...document.querySelectorAll('fieldset')].some(e => e.querySelector('legend')?.textContent === " + json.dumps(profile) + " && e.querySelector('[role=status]')?.textContent === " + json.dumps(expected) + ");", timeout=timeout)


def test_gui_owned_tts_asr_stop_and_restart_off(tmp_path):
    sys.path.insert(0, str(ROOT / 'tests/voice'))
    from ui_entry_acceptance import FixtureServer

    binary = bundled_binary()
    models = {name: Path(os.environ[variable]).resolve(strict=True) for name, variable in (
        ('tts', 'VRCT_QWEN_TTS_MODEL'), ('asr', 'VRCT_SPEECH_ASR_MODEL'), ('vad', 'VRCT_SPEECH_VAD_MODEL'))}
    with wave.open(os.environ['VRCT_SPEECH_ASR_INPUT'], 'rb') as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
        pcm = wav.readframes(wav.getnframes())
    report = dict(status='failed', bundled_version='0.10.0', native_gui=True, private_audio=True,
                  physical_capture=False, vrchat=False, perceptual_quality=False)
    trace = tmp_path / 'voice.jsonl'

    def traces():
        return [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []

    def alive(process):
        import psutil
        try:
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    def owned(ui):
        return [p for p in ui.app_process.children(recursive=True) if alive(p) and p.exe() == str(binary)]

    try:
        with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
            loopback(stack, 'vrct.native.caption')
            producer = stack.enter_context(SyntheticProducer(pcm))
            capture = ToneCapture(stack, SOURCE)
            gate = PipeWireGate()
            external = FixtureServer()
            external.start()
            stack.callback(external.stop)
            state = initial_state(tmp_path)
            config_path = state / 'config.json'
            config = json.loads(config_path.read_text())
            config['SELECTED_YOUR_LANGUAGES'] = {str(tab): {str(slot): dict(language='English', country='United States', enable=slot == 1)
                                                         for slot in range(1, 4)} for tab in range(1, 6)}
            config_path.write_text(json.dumps(config))
            with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state), 'VRCT_VOICE_TRACE': str(trace.resolve())}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                open_voice(ui)
                assert not owned(ui)
                fill(ui, 'Multilingual TTS', 'Model GGUF path', models['tts'])
                fill(ui, 'ASR + VAD', 'Model GGUF path', models['asr'])
                fill(ui, 'ASR + VAD', 'VAD GGUF path', models['vad'])
                ui.click_text('button', 'Save changes')
                wait_for(lambda: json.loads(config_path.read_text()).get('SPEECH_SERVER_SETTINGS', {}).get('profiles', {}).get('asr', {}).get('vad_model') == str(models['vad']))
                assert not owned(ui), 'saving started a model'
                started = time.monotonic()
                button(ui, 'Multilingual TTS', 'Start server')
                server_state(ui, 'Multilingual TTS', 'Ready')
                report['tts_gui_start_to_ready_s'] = time.monotonic() - started
                started = time.monotonic()
                button(ui, 'ASR + VAD', 'Start server')
                server_state(ui, 'ASR + VAD', 'Ready')
                report['asr_gui_start_to_ready_s'] = time.monotonic() - started
                children = owned(ui)
                assert len(children) == 2
                ui.select('Audio route', 'managed')
                ui.select('Read aloud', 'original')
                ui.fill('Other languages server (Qwen3-TTS)', external.url)
                ui.select('Other languages server', 'bundled')
                ui.click_text('button', 'Save changes')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Muted (confirmed)')")
                ui.click_text('button', 'Resume voice')
                wait_for(lambda: not gate.inspect()['muted'])
                ui.close_settings()

                def send(text):
                    element = ui.command('POST', '/element', {'using': 'css selector', 'value': 'textarea'})
                    ui.element_command(element, 'value', {'text': text})
                    at = time.monotonic_ns()
                    ui.click('[class*="message_send_button"]')
                    ui.wait("return document.querySelector('textarea').value === ''")
                    return at

                def audio_after(at):
                    with capture.lock:
                        return next((t for t, _, nonzero in capture.history if t >= at and nonzero), None)

                at = send('Hello. This is the bundled speech server test.')
                first = wait_for(lambda: audio_after(at), timeout=30, code='owned_tts_no_audio')
                wait_for(lambda: len(traces()) == 1, timeout=30)
                assert traces()[0]['outcome'] == 'completed'
                settled(capture, time.monotonic_ns(), 'owned_tts_completion_not_silent', silent=True)
                assert not external.requests
                report['tts_click_to_private_audio_ms'] = (first - at) / 1e6
                report['tts_completed_requests'] = 1
                # Stop a real model during an active request, not just an idle process.
                at = send('This is a long interruption test. Please keep reading these words until the server is stopped. ' * 10)
                wait_for(lambda: audio_after(at), timeout=30, code='owned_tts_long_no_audio')
                open_voice(ui)
                at = time.monotonic_ns()
                button(ui, 'Multilingual TTS', 'Stop server')
                silent = settled(capture, at, 'owned_tts_stop_not_silent', silent=True)
                server_state(ui, 'Multilingual TTS', 'Stopped', timeout=5)
                wait_for(lambda: len(owned(ui)) == 1)
                wait_for(lambda: len(traces()) == 2)
                assert traces()[-1]['outcome'] == 'cancelled'
                report['tts_stop_call_to_private_silence_ms'] = (silent - at) / 1e6
                report['silence_confirmation_ms'] = 2000
                ui.close_settings()
                at = send('The stopped bundled server must stay silent.')
                wait_for(lambda: len(traces()) == 3)
                assert traces()[-1]['outcome'] == 'error' and not external.requests
                settled(capture, at, 'owned_tts_external_fallback', silent=True)
                # The separately owned ASR remains available after stopping TTS.
                open_captions(ui)
                ui.select('ASR server', 'bundled')
                ui.click_text('button', 'Save caption settings')
                model = ui.wait("const e = [...document.querySelectorAll('label')].find(e => e.firstChild.textContent.trim() === 'ASR model')?.querySelector('select'); return e && [...e.options].find(o => o.value && !o.textContent.includes('(Unavailable)'))?.value;")
                ui.select('ASR model', model)
                endpoint = next(row['endpoint'] for row in enumerate_endpoints('mic') if row['endpoint'].name == 'vrct.native.caption.source')
                ui.select('Microphone input', json.dumps([str(endpoint.cookie), str(endpoint.serial), endpoint.name, endpoint.media_class], separators=(',', ':')))
                ui.click_text('button', 'Save caption settings')
                wait_for(lambda: json.loads(config_path.read_text()).get('REALTIME_ASR_SETTINGS', {}).get('model') == model)
                ui.click_text('button', 'Start microphone captions')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Captions running')")
                ui.close_settings()
                instrument_rows(ui)
                baseline_rows = ui.evaluate('return window.__captionRows.length')
                assert producer.play().wait(10)
                ui.wait(f"return window.__captionRows.length >= {baseline_rows + 2}", timeout=25)
                report['new_caption_rows'] = ui.evaluate('return window.__captionRows.length') - baseline_rows
                open_voice(ui)
                in_flight = producer.play()
                button(ui, 'ASR + VAD', 'Stop server')
                server_state(ui, 'ASR + VAD', 'Stopped', timeout=5)
                wait_for(lambda: not any(name.startswith('vrct.asr.capture.') for name in nodes()))
                wait_for(lambda: not owned(ui))
                ui.close_settings()
                previous = ui.evaluate("return document.querySelector('#log_container').innerText")
                # The producer serializes utterances. Await the one intentionally
                # in flight at Stop before timing a new post-Stop utterance.
                assert in_flight.wait(10)
                assert producer.play().wait(10)
                assert ui.evaluate("return document.querySelector('#log_container').innerText") == previous
                # Actual loading cancellation; no capture restarts with it.
                open_voice(ui)
                button(ui, 'ASR + VAD', 'Start server')
                button(ui, 'ASR + VAD', 'Stop server')
                server_state(ui, 'ASR + VAD', 'Stopped', timeout=5)
                wait_for(lambda: not owned(ui))
                ui.close_app()
                assert not any(alive(p) for p in children)
            assert gate.inspect()['muted']
            with NativeWebDriver(tmp_path / 'restart', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                open_voice(ui)
                for name in ('Japanese TTS', 'Multilingual TTS', 'ASR + VAD'):
                    server_state(ui, name, 'Stopped', timeout=5)
                assert not owned(ui)
                assert ui.evaluate('return arguments[0].value', control(ui, 'ASR + VAD', 'VAD GGUF path')) == str(models['vad'])
                assert ui.evaluate('return arguments[0].value', ui.control('Other languages server')) == 'bundled'
                assert not any(name.startswith('vrct.asr.capture.') for name in nodes())
                assert gate.inspect()['muted']
                ui.close_app()
            conn = http.client.HTTPConnection('127.0.0.1', external.port, timeout=2)
            try:
                conn.request('GET', '/')
                assert conn.getresponse().status == 501  # Fixture has POST only, but remains responsive.
            finally:
                conn.close()
            assert external.thread.is_alive() and not external.requests
            report.update(status='passed', external_server_preserved=True, restart_servers_and_capture_off=True, traces=traces())
    finally:
        (tmp_path / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
