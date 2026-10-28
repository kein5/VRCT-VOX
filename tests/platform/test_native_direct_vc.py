"""Actual product controls with consented Seed and private synthetic audio only."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import time
import wave

import pytest

from native_webdriver import NativeWebDriver, ROOT
from test_native_ui import initial_state
from test_native_realtime import SyntheticProducer
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE, TTS_SINK
from models.audio_routing.source_bridge import select_source
from tools.voice_acceptance import graph_snapshot, loopback, nodes, private_graph, stop_process, wait_for
from tools.voice_b_poc import Producer, ToneCapture, settled

pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_DIRECT_VC') != '1',
                               reason='approved Seed, native app and display guard required')


def test_native_converted_controls_stop_replacement_and_restart(tmp_path):
    runtime = Path(os.environ['VRCT_SEED_POC']).resolve()
    reference = runtime / 'private-inputs/reference.wav'
    with wave.open(str(runtime/'private-inputs/input.wav')) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
        pcm = wav.readframes(wav.getnframes())
    report = dict(status='failed', native_tauri=True, real_seed=True, physical_capture=False,
                  vrchat=False, subjective_quality=False, actual_asr=False, actual_tts=False,
                  tts_branch='independent synthetic 880Hz producer', cases=[])
    try:
        with private_graph(config_fragment=ROOT/'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
            input_node = loopback(stack, 'vrct.native.caption')
            producer = stack.enter_context(SyntheticProducer(pcm))
            original = ToneCapture(stack, 'vrct.native.caption.source')
            settled(original, time.monotonic_ns(), 'input_not_stable', silent=True)
            capture = ToneCapture(stack, SOURCE)
            gate = PipeWireGate()
            state = initial_state(tmp_path)
            def selected():
                source = select_source(graph_snapshot(), 'vrct.native.caption.source')
                return json.dumps([str(source.cookie), str(source.serial), source.name, source.media_class], separators=(',', ':'))
            with NativeWebDriver(tmp_path/'first', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()
                ui.select('Audio route', 'managed')
                ui.click_text('button', 'Save voice settings')
                wait_for(lambda: json.loads((state/'config.json').read_text())['VOICE_SETTINGS']['routing'] == 'managed')
                ui.select('Direct voice mode', 'converted')
                ui.fill('Seed runtime folder', str(runtime))
                ui.fill('Permitted reference WAV', str(reference))
                ui.click_text('button', 'Save input settings')
                wait_for(lambda: json.loads((state/'config.json').read_text()).get('DIRECT_VOICE_SETTINGS', {}).get('mode') == 'converted')
                assert not any(name.startswith('vrct.asr.capture.') for name in nodes())
                assert gate.inspect()['muted']
                ui.select('Input to forward', selected())
                ui.click_text('button', 'Start input forwarding')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => ['VC active; no speech detected','VC ready; conversion not yet confirmed'].includes(e.textContent))", timeout=65)
                settled(capture, time.monotonic_ns(), 'preparing_not_silent', silent=True)
                ui.click_text('button', 'Resume voice')
                finished = producer.play()
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Converting voice')", timeout=15)
                wait_for(lambda: capture.snapshot()['nonzero_frames'] > 5)
                assert finished.wait(12)
                settled(capture, time.monotonic_ns(), 'end_of_utterance_not_silent', silent=True)
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'VC active; no speech detected')")
                report['cases'].append('full_synthetic_utterance_then_idle')
                # Stop during a second utterance; observe the private source.
                producer.play()
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Converting voice')", timeout=15)
                before = time.monotonic_ns()
                ui.click_text('button', 'Stop input forwarding')
                silence = settled(capture, before, 'explicit_stop_not_silent', silent=True)
                report['stop_to_silent_read_ms'] = (silence-before)/1e6
                report['cases'].append('stop_during_speech_silent_for_2s')
                wait_for(lambda: not any(name.startswith('vrct.asr.capture.') for name in nodes()))
                assert SOURCE in nodes()
                # Independent TTS branch remains usable across source failure.
                tts = Producer(stack, TTS_SINK, 880)
                settled(capture, time.monotonic_ns(), 'tts_branch_not_audible', present=(880,))
                ui.wait("return [...document.querySelectorAll('button')].some(e => e.textContent === 'Start input forwarding' && !e.disabled)")
                ui.click_text('button', 'Start input forwarding')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => ['VC active; no speech detected','VC ready; conversion not yet confirmed','Converting voice'].includes(e.textContent))", timeout=65)
                stop_process(input_node)
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Input forwarding failed and stopped')")
                producer.token.cancel()
                producer.thread.join(3)
                assert not producer.thread.is_alive()
                assert all(error == 'SpeechError' for error in producer.errors), producer.errors
                producer.errors.clear()  # Expected producer disconnect, not a product failure.
                loopback(stack, 'vrct.native.caption')
                Producer(stack, 'vrct.native.caption.sink', 440)
                settled(capture, time.monotonic_ns(), 'replacement_forwarded_raw', present=(880,), absent=(440,))
                ui.click_text('button', 'Refresh inputs')
                ui.wait("return [...document.querySelectorAll('select option:checked')].some(e => e.textContent === 'Disconnected')")
                assert ui.evaluate('return arguments[0].disabled', ui.control('Input to forward')) is False
                assert not any(name.startswith('vrct.asr.capture.') for name in nodes())
                report['cases'].append('source_replacement_no_reconnect_tts_continues')
                tts.close()
                settled(capture, time.monotonic_ns(), 'tts_end_not_silent', silent=True)
                ui.assert_rendered()
                ui.close_app()
            with NativeWebDriver(tmp_path/'restart', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()
                assert ui.evaluate('return arguments[0].value', ui.control('Direct voice mode')) == 'converted'
                assert ui.evaluate('return arguments[0].value', ui.control('Seed runtime folder')) == str(runtime)
                assert ui.evaluate('return arguments[0].value', ui.control('Input to forward')) == ''
                assert gate.inspect()['muted'] and not any(name.startswith('vrct.asr.capture.') for name in nodes())
                ui.close_app()
            report.update(status='passed', capture=capture.snapshot(), restart_muted_without_capture=True,
                          model_download=False, shared_endpoint_preserved=True)
    finally:
        (tmp_path/'report.json').write_text(json.dumps(report, indent=2)+'\n')
