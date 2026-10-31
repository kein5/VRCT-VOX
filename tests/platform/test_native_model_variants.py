"""Actual native send -> real model -> sample-exact private source at model rate.

Qwen is tested at 24 kHz to avoid treating intentional 48 kHz resampling as
corruption. These cases do not validate the host's resampling or physical audio.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from native_webdriver import ROOT, NativeWebDriver
from native_voice_measurement import exact_pcm
from test_native_ui import initial_state
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
from tools.live_tts_acceptance import SpeechServer, SHORT
from tools.voice_acceptance import private_graph, wait_for
from tools.vrchat_gui_probe import Capture

pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_VARIANTS') != '1',
                               reason='explicit native GUI and downloaded GPU models required')


@pytest.mark.parametrize('model_id', ['irodori-v41-q8', 'qwen3-06b-q5', 'qwen3-06b-q8'])
def test_native_variant_pcm_matches_independent_reference(tmp_path, model_id):
    evidence = Path(os.environ['VRCT_TEST_VARIANT_EVIDENCE'])
    prior = json.loads((evidence / 'report.json').read_text())
    row = next(r for r in prior['models'] if r['id'] == model_id)
    assert row['status'] == 'passed'
    rate = row['requests'][0]['rate']
    reference = (evidence / model_id / row['requests'][0]['file']).read_bytes()
    report = dict(status='failed', model_id=model_id, rate=rate, native_gui=True,
                  real_inference=True, physical_audio=False, host_resampling_tested=False, cases=[])
    try:
        with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf', rate=rate), ExitStack() as stack:
            server = SpeechServer(SimpleNamespace(model=Path(row['path']), output=tmp_path,
                speech_binary=os.environ['VRCT_TEST_SPEECH_BINARY'], device='Vulkan0', seed=42))
            stack.callback(server.stop)
            server.start()
            gate = PipeWireGate()
            state = initial_state(tmp_path)
            config = state / 'config.json'
            values = json.loads(config.read_text())
            values['VOICE_SETTINGS'] = {'japanese_seed': '42'}
            config.write_text(json.dumps(values))
            trace = tmp_path / 'trace.jsonl'
            with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state), 'VRCT_VOICE_TRACE': str(trace)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_route_settings()
                ui.select('Audio route', 'managed')
                ui.click_text('button', 'Save changes')
                wait_for(lambda: json.loads(config.read_text()).get('VOICE_SETTINGS', {}).get('routing') == 'managed')
                ui.click_text('button', 'Resume voice')
                wait_for(lambda: not gate.inspect()['muted'])
                ui.open_voice_settings()
                ui.select('Chat voice', 'original')
                ui.select('Japanese server', 'external')
                ui.fill('Japanese server (Irodori)', server.url)
                ui.fill('Japanese voice name', row['voice'])
                ui.click_text('button', 'Save changes')
                wait_for(lambda: json.loads(config.read_text()).get('VOICE_SETTINGS', {}).get('japanese_voice') == row['voice'])
                ui.close_settings()
                ui.click('[role=switch][aria-label=TTS]')
                ui.wait("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked')==='true'")
                for index in range(2):
                    recording = Capture(SOURCE, tmp_path / f'case-{index}.pcm', rate=rate)
                    try:
                        time.sleep(.3)
                        field = ui.evaluate("return [...document.querySelectorAll('textarea')].find(e => getComputedStyle(e).visibility === 'visible' && e.getClientRects().length)")
                        ui.element_command(field, 'clear')
                        ui.element_command(field, 'value', {'text': SHORT})
                        ui.click('[class*=message_send_button]')
                        wait_for(lambda: trace.exists() and len(trace.read_text().splitlines()) == index + 1, timeout=25)
                        time.sleep(2)
                    finally:
                        validation = recording.close()
                    assert validation['valid'], validation
                    matched = exact_pcm(reference, (tmp_path / f'case-{index}.pcm').read_bytes())
                    report['cases'].append(dict(index=index, capture=validation, exact_pcm=matched))
                    assert matched['valid'], matched
                assert all(json.loads(line)['outcome'] == 'completed' for line in trace.read_text().splitlines())
                ui.close_app()
            assert gate.inspect()['muted']
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        (tmp_path / 'report.json').write_text(json.dumps(report, indent=2))
