"""Real Irodori standby, native cancellation and restart on private audio."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import time

import pytest

from native_webdriver import NativeWebDriver, ROOT
from test_native_ui import initial_state
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
from models.speech_server.settings import normalize_settings
from tools.live_tts_acceptance import SHORT, LONG
from tools.managed_vrchat_probe import require_continuous_capture
from tools.voice_acceptance import private_graph, wait_for
from tools.voice_b_poc import ToneCapture, settled

pytestmark = pytest.mark.skipif(
    os.environ.get('VRCT_TEST_NATIVE_LOW_LATENCY_CONTROLS') != '1',
    reason='explicit native GUI, GPU and existing Irodori model required')


def test_standby_active_stop_toggle_mute_and_restart(tmp_path):
    state = initial_state(tmp_path)
    path = state / 'config.json'
    config = json.loads(path.read_text())
    config['SPEECH_SERVER_SETTINGS'] = normalize_settings({'profiles': {'japanese': {
        'model': str(Path(os.environ['VRCT_TEST_SPEECH_MODEL']).resolve(strict=True)),
        'device': 'gpu', 'low_latency': True}}})
    config.setdefault('VOICE_SETTINGS', {})['japanese_seed'] = '42'
    path.write_text(json.dumps(config))
    trace = tmp_path / 'trace.jsonl'
    report = dict(status='failed', native_gui=True, real_inference=True,
                  host_audio_changed=False, physical_hearing=False,
                  silence_peak_threshold_s16=64, cases=[])

    def traces():
        return [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []

    try:
        with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
            monitor = ToneCapture(stack, SOURCE)
            gate = PipeWireGate()
            with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state), 'VRCT_VOICE_TRACE': str(trace)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_route_settings()
                ui.select('Audio route', 'managed')
                ui.click_text('button', 'Save audio route')
                wait_for(lambda: json.loads(path.read_text()).get('VOICE_SETTINGS', {}).get('routing') == 'managed')
                ui.click_text('button', 'Resume voice')
                wait_for(lambda: not gate.inspect()['muted'])
                ui.open_voice_settings()
                ui.click_text('button', 'Start server')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Low-latency standby active')", timeout=120)
                ui.select('Chat voice', 'original')
                ui.select('Japanese server', 'bundled')
                ui.click_text('button', 'Save voice settings')
                wait_for(lambda: json.loads(path.read_text()).get('VOICE_SETTINGS', {}).get('mode') == 'original')
                ui.close_settings()
                ui.click('[role=switch][aria-label=TTS]')
                ui.wait("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked')==='true'")

                def send(text):
                    field = ui.evaluate("return [...document.querySelectorAll('textarea')].find(e => getComputedStyle(e).visibility === 'visible' && e.getClientRects().length)")
                    ui.element_command(field, 'clear')
                    ui.element_command(field, 'value', {'text': text})
                    start = time.monotonic_ns()
                    ui.click('[class*=message_send_button]')
                    ui.wait("return document.querySelector('textarea[class*=message_box_input_area]').value===''")
                    return start

                def silence(name, action):
                    count = len(traces())
                    before = monitor.snapshot()
                    require_continuous_capture(before)
                    start = time.monotonic_ns()
                    action()
                    settled(monitor, start, name, silent=True)
                    after = monitor.snapshot()
                    require_continuous_capture(after)
                    assert monitor.process.poll() is None and monitor.thread.is_alive()
                    assert after['sample_count'] - before['sample_count'] >= 48000 * 2
                    assert after['nonzero_frames'] == before['nonzero_frames'], name
                    assert len(traces()) == count
                    report['cases'].append(dict(name=name, silence_ms=2000, action_ns=start,
                                               before=before, after=after))

                for action in ('stop', 'tts_off', 'held_mute', 'server_stop'):
                    count = len(traces())
                    prior = monitor.snapshot()['nonzero_frames']
                    send(LONG)
                    wait_for(lambda: monitor.snapshot()['nonzero_frames'] > prior, timeout=20)
                    if action in ('stop', 'server_stop'):
                        ui.open_voice_settings()
                    elif action == 'held_mute':
                        ui.open_route_settings()
                    at = time.monotonic_ns()
                    if action == 'tts_off':
                        ui.click('[role=switch][aria-label=TTS]')
                    else:
                        ui.click_text('button', {'stop': 'Stop playback and clear queue',
                                               'held_mute': 'Mute until resumed',
                                               'server_stop': 'Stop server'}[action])
                    silent = settled(monitor, at, action + '_not_silent', silent=True)
                    wait_for(lambda: len(traces()) == count + 1, timeout=8)
                    assert traces()[-1]['outcome'] == 'cancelled', traces()[-1]
                    require_continuous_capture(monitor.snapshot())
                    report['cases'].append(dict(name=action, call_to_silence_ms=(silent-at)/1e6,
                                               silence_ms=2000, trace=traces()[-1]))
                    if action != 'tts_off':
                        ui.close_settings()
                    if action == 'tts_off':
                        silence('off_rejects_new', lambda: send(SHORT))
                        silence('reenable_no_stale_replay', lambda: ui.click('[role=switch][aria-label=TTS]'))
                    if action == 'held_mute':
                        assert gate.inspect()['muted']
                        silence('held_mute_rejects_new', lambda: send(SHORT))
                        ui.open_route_settings()
                        ui.click_text('button', 'Resume voice')
                        wait_for(lambda: not gate.inspect()['muted'])
                        ui.close_settings()
                ui.open_voice_settings()
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Stopped')")
                assert not ui.evaluate("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Low-latency standby active')")
                # A fresh start must also be cancelled while the model is loading.
                ui.click_text('button', 'Start server')
                ui.click_text('button', 'Stop server')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Stopped')", timeout=15)
                ui.close_app()
            assert gate.inspect()['muted']
            with NativeWebDriver(tmp_path / 'restart', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                assert ui.evaluate("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked')") == 'false'
                ui.open_voice_settings()
                assert json.loads(path.read_text())['SPEECH_SERVER_SETTINGS']['profiles']['japanese']['low_latency'] is True
                assert not ui.evaluate("return [...document.querySelectorAll('[role=status]')].some(e => ['Ready','Low-latency standby active'].includes(e.textContent))")
                assert gate.inspect()['muted']
                ui.close_app()
            report.update(capture=monitor.snapshot(), restart_off=True)
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        (tmp_path / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
