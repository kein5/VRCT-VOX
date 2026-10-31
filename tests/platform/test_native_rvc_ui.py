"""Real RVC through native product controls, using consented synthetic input."""
from contextlib import ExitStack
import ast
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
from tools.managed_vrchat_probe import require_continuous_capture
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
                  vrchat=False, perceptual_quality=False, index_rate=.5,
                  silence_peak_threshold_s16=64)
    try:
        with private_graph(config_fragment=ROOT/'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
            loopback(stack, 'vrct.native.caption')
            producer = stack.enter_context(SyntheticProducer(pcm))
            original = ToneCapture(stack, 'vrct.native.caption.source')
            settled(original, time.monotonic_ns(), 'input_not_stable', silent=True)
            capture = ToneCapture(stack, SOURCE)
            gate = PipeWireGate()
            state = initial_state(tmp_path)

            def active_status(after_ns):
                def fresh():
                    path = state / 'logs/process.log'
                    if not path.exists():
                        return None
                    with path.open('rb') as log:
                        log.seek(max(0, path.stat().st_size - 160000))
                        lines = log.read().decode(errors='replace').splitlines()
                    for line in reversed(lines):
                        if "'endpoint': '/get/data/direct_voice_state'" in line:
                            value = ast.literal_eval(line.split(' - INFO - ', 1)[1])['result']
                            observed = int(value['observation_id'])
                            return value if after_ns < observed <= time.monotonic_ns() and time.monotonic_ns() - observed < 2_000_000_000 else None
                    return None
                value = wait_for(fresh, timeout=5)
                assert value['active'] and value['requested'] and not value['error'], value
                return value

            source = select_source(graph_snapshot(), 'vrct.native.caption.source')
            selected = json.dumps([str(source.cookie), str(source.serial), source.name, source.media_class], separators=(',', ':'))
            with NativeWebDriver(tmp_path/'first', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_rvc_settings()
                ui.click_text('button', 'Prepare and use virtual microphone')
                wait_for(lambda: json.loads((state/'config.json').read_text())['VOICE_SETTINGS']['routing'] == 'managed')
                ui.fill('RVC runtime folder', runtime)
                ui.fill('Permitted RVC model (.pth)', model)
                ui.fill('RVC retrieval index (.index, optional)', index)
                ui.fill('Retrieval blend (0–1)', '0.5')
                ui.click_text('button', 'Save changes')
                wait_for(lambda: json.loads((state/'config.json').read_text()).get('DIRECT_VOICE_SETTINGS', {}).get('engine') == 'rvc')
                assert gate.inspect()['muted'] and not any(name.startswith('vrct.asr.capture.') for name in nodes())
                ui.select('Input to forward', selected)
                ui.click_text('button', 'Start input forwarding')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => ['VC ready; conversion not yet confirmed','Converting voice'].includes(e.textContent))", timeout=65)
                settled(capture, time.monotonic_ns(), 'rvc_bypassed_global_mute', silent=True)
                status_before = active_status(time.monotonic_ns())
                muted_before, input_before = capture.snapshot(), original.snapshot()
                muted_at = time.monotonic_ns()
                assert gate.inspect()['muted']
                finished = producer.play()
                wait_for(lambda: original.snapshot()['nonzero_frames'] > input_before['nonzero_frames'] + 10)
                wait_for(finished.is_set, timeout=len(pcm) / 96000 + 8)
                finished_at = time.monotonic_ns()
                settled(original, finished_at, 'muted_input_not_drained', silent=True)
                settled(capture, finished_at, 'muted_output_not_drained', silent=True)
                muted_after, input_after = capture.snapshot(), original.snapshot()
                for observer in (capture, original):
                    require_continuous_capture(observer.snapshot())
                    assert observer.process.poll() is None and observer.thread.is_alive()
                assert producer.thread.is_alive() and not producer.errors
                assert muted_after['nonzero_frames'] == muted_before['nonzero_frames']
                assert muted_after['sample_count'] - muted_before['sample_count'] >= len(pcm) // 2
                assert gate.inspect()['muted']
                status_after = active_status(time.monotonic_ns())
                assert status_after['generation'] == status_before['generation']
                report['mute_with_nonzero_input'] = dict(
                    action_ns=muted_at, producer_finished_ns=finished_at,
                    input_before=input_before, input_after=input_after,
                    output_before=muted_before, output_after=muted_after,
                    producer_finished=True, gate_muted=True,
                    status_before=status_before, status_after=status_after)
                ui.click_text('button', 'Resume voice')
                baseline = capture.snapshot()['nonzero_frames']
                input_baseline = original.snapshot()['nonzero_frames']
                finished = producer.play()
                wait_for(lambda: original.snapshot()['nonzero_frames'] > input_baseline + 10)
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Converting voice')", timeout=10)
                wait_for(lambda: capture.snapshot()['nonzero_frames'] > baseline+10, timeout=10)
                wait_for(finished.is_set, timeout=len(pcm) / 96000 + 8)
                resumed = active_status(time.monotonic_ns())
                assert resumed['generation'] == status_before['generation']
                report['resume_full_input'] = dict(status_after=resumed,
                                                 output_nonzero_delta=capture.snapshot()['nonzero_frames'] - baseline,
                                                 producer_finished=True)
                # Stop during a fresh nonzero input, after the complete resumed
                # fixture has proven that the original late failure is gone.
                baseline = capture.snapshot()['nonzero_frames']
                input_baseline = original.snapshot()['nonzero_frames']
                producer.play()
                wait_for(lambda: original.snapshot()['nonzero_frames'] > input_baseline + 10)
                wait_for(lambda: capture.snapshot()['nonzero_frames'] > baseline + 10, timeout=10)
                before = time.monotonic_ns()
                ui.click_text('button', 'Stop input forwarding')
                silent = settled(capture, before, 'rvc_ui_stop_not_silent', silent=True)
                report['stop_to_silent_read_ms'] = (silent-before)/1e6
                wait_for(lambda: not any(name.startswith('vrct.asr.capture.') for name in nodes()))
                ui.assert_rendered()
                ui.close_app()
            with NativeWebDriver(tmp_path/'restart', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_rvc_settings()
                assert ui.evaluate('return arguments[0].value', ui.control('Permitted RVC model (.pth)')) == model
                assert ui.evaluate('return arguments[0].value', ui.control('Input to forward')) == ''
                assert gate.inspect()['muted'] and not any(name.startswith('vrct.asr.capture.') for name in nodes())
                ui.close_app()
            require_continuous_capture(capture.snapshot())
            require_continuous_capture(original.snapshot())
            report.update(capture=capture.snapshot(), original_capture=original.snapshot(),
                          restart_off=True, silence_hold_ms=2000)
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        (tmp_path/'report.json').write_text(json.dumps(report, indent=2)+'\n')
