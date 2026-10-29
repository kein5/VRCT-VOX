"""Real RVC through native product controls, using consented synthetic input."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import time
import wave

import pytest

from native_webdriver import NativeWebDriver, ROOT
from test_native_ui import initial_state
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
from models.audio_routing.source_bridge import select_source
from tools.voice_acceptance import graph_snapshot, loopback, nodes, private_graph, wait_for
from tools.voice_b_poc import ToneCapture, settled

pytestmark = pytest.mark.skipif(sys.platform != 'linux' or os.environ.get('VRCT_TEST_NATIVE_RVC_UI') != '1',
                               reason='consented RVC model, native build and display guard required')


def test_native_rvc_selection_real_conversion_stop_and_restart(tmp_path):
    from test_native_realtime import SyntheticProducer
    runtime = str(Path(os.environ['VRCT_RVC_RUNTIME']).resolve())
    model = str(Path(os.environ['VRCT_RVC_MODEL']).resolve())
    index = str(Path(os.environ['VRCT_RVC_INDEX']).resolve())
    with wave.open(os.environ['VRCT_RVC_INPUT']) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
        pcm = wav.readframes(wav.getnframes())
    report = dict(status='failed', native_tauri=True, real_rvc=True, physical_capture=False,
                  vrchat=False, perceptual_quality=False, index_rate=.5)
    try:
        with private_graph(config_fragment=ROOT/'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
            loopback(stack, 'vrct.native.caption')
            producer = stack.enter_context(SyntheticProducer(pcm))
            original = ToneCapture(stack, 'vrct.native.caption.source')
            settled(original, time.monotonic_ns(), 'input_not_stable', silent=True)
            capture = ToneCapture(stack, SOURCE)
            gate = PipeWireGate()
            state = initial_state(tmp_path)
            source = select_source(graph_snapshot(), 'vrct.native.caption.source')
            selected = json.dumps([str(source.cookie), str(source.serial), source.name, source.media_class], separators=(',', ':'))
            with NativeWebDriver(tmp_path/'first', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()
                ui.select('Audio route', 'managed')
                ui.click_text('button', 'Save voice settings')
                wait_for(lambda: json.loads((state/'config.json').read_text())['VOICE_SETTINGS']['routing'] == 'managed')
                ui.select('Direct voice mode', 'converted')
                ui.select('VC engine', 'rvc')
                ui.fill('RVC runtime folder', runtime)
                ui.fill('Permitted RVC model (.pth)', model)
                ui.fill('RVC retrieval index (.index, optional)', index)
                ui.fill('Retrieval blend (0–1)', '0.5')
                ui.click_text('button', 'Save input settings')
                wait_for(lambda: json.loads((state/'config.json').read_text()).get('DIRECT_VOICE_SETTINGS', {}).get('engine') == 'rvc')
                assert gate.inspect()['muted'] and not any(name.startswith('vrct.asr.capture.') for name in nodes())
                ui.select('Input to forward', selected)
                ui.click_text('button', 'Start input forwarding')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => ['VC ready; conversion not yet confirmed','Converting voice'].includes(e.textContent))", timeout=65)
                settled(capture, time.monotonic_ns(), 'rvc_bypassed_global_mute', silent=True)
                ui.click_text('button', 'Resume voice')
                baseline = capture.snapshot()['nonzero_frames']
                producer.play()
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Converting voice')", timeout=10)
                wait_for(lambda: capture.snapshot()['nonzero_frames'] > baseline+10, timeout=10)
                before = time.monotonic_ns()
                ui.click_text('button', 'Stop input forwarding')
                silent = settled(capture, before, 'rvc_ui_stop_not_silent', silent=True)
                report['stop_to_silent_read_ms'] = (silent-before)/1e6
                wait_for(lambda: not any(name.startswith('vrct.asr.capture.') for name in nodes()))
                ui.assert_rendered()
                ui.close_app()
            with NativeWebDriver(tmp_path/'restart', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()
                assert ui.evaluate('return arguments[0].value', ui.control('VC engine')) == 'rvc'
                assert ui.evaluate('return arguments[0].value', ui.control('Permitted RVC model (.pth)')) == model
                assert ui.evaluate('return arguments[0].value', ui.control('Input to forward')) == ''
                assert gate.inspect()['muted'] and not any(name.startswith('vrct.asr.capture.') for name in nodes())
                ui.close_app()
            report.update(status='passed', capture=capture.snapshot(), restart_off=True, silence_hold_ms=2000)
    finally:
        (tmp_path/'report.json').write_text(json.dumps(report, indent=2)+'\n')
