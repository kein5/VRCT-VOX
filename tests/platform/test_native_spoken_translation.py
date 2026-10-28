"""Native UI + real ASR/VAD/Qwen TTS; deterministic HTTP translation, private PCM."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from types import SimpleNamespace
import wave

import numpy as np
import pytest
import soxr

from native_webdriver import NativeWebDriver, ROOT
from test_native_realtime import SyntheticProducer, TranslationFixture, open_captions
from test_native_ui import initial_state
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE, VC_SINK
from models.transcription.capture_pipewire import enumerate_endpoints
from models.transcription.realtime_settings import endpoint_dict, normalize_settings
from models.transcription.speechcpp_asr import ASRError, SpeechCppASR
from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS
from tools.live_tts_acceptance import SpeechServer
from tools.voice_acceptance import loopback, nodes, private_graph, stop_process, wait_for
from tools.voice_b_poc import Producer, ToneCapture, ToneObservation, settled
from tools.vrchat_audio_probe import compare_pcm
from tools.vrchat_gui_probe import Capture

pytestmark = pytest.mark.skipif(
    os.environ.get('VRCT_TEST_NATIVE_GUI') != '1' or not os.environ.get('VRCT_QWEN_TTS_MODEL'),
    reason='opt-in native GUI and existing ASR/VAD/Qwen files required',
)
TEXTS = ['The green bird is singing.', 'Please close the heavy door.']


def open_voice(ui):
    ui.assert_rendered()
    # Network isolation deliberately triggers this notification over Settings.
    # Dismiss its actual close control; never bypass WebDriver hit testing.
    notice = ui.evaluate("return [...document.querySelectorAll('.Toastify__toast')].find(e => e.textContent.startsWith('Network is not connected.'))?.querySelector('button svg')")
    if notice:
        ui.element_command(notice, 'click')
    ui.open_voice_settings()


@pytest.mark.parametrize('direct_policy', ['suppress', 'mix'])
def test_native_mic_translation_to_qwen_once_and_source_stop(tmp_path, direct_policy):
    binary = Path(os.environ['VRCT_SPEECH_BINARY']).resolve(strict=True)
    models = [Path(os.environ[name]).resolve(strict=True)
              for name in ('VRCT_SPEECH_ASR_MODEL', 'VRCT_SPEECH_VAD_MODEL')]
    qwen = Path(os.environ['VRCT_QWEN_TTS_MODEL']).resolve(strict=True)
    with wave.open(os.environ['VRCT_SPEECH_ASR_INPUT'], 'rb') as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
        pcm = wav.readframes(wav.getnframes())
    report = {'status': 'failed', 'native_ui': True, 'real_asr_vad_tts': True,
              'real_translation_model': False, 'translation': 'fixed local HTTP via production LMStudio adapter',
              'physical_capture': False, 'vrchat': False, 'gpu_contention_measured': False,
              'direct_policy': direct_policy, 'direct_input': 'continuous synthetic 440 Hz',
              'shared_physical_capture_verified': False}
    direct = {'silent': True} if direct_policy == 'suppress' else {'present': (440,)}
    trace = tmp_path / 'voice.jsonl'
    def traces():
        return [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    try:
        with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
            loopback(stack, 'vrct.native.caption')
            producer = stack.enter_context(SyntheticProducer(pcm))
            translation = stack.enter_context(TranslationFixture(TEXTS))
            osc = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            osc.bind(('127.0.0.2', 0))
            osc.setblocking(False)
            Producer(stack, VC_SINK, 440)  # Continuous direct-path substitute, never a real microphone.
            capture = ToneCapture(stack, SOURCE)
            gate = PipeWireGate()
            log = stack.enter_context((tmp_path / 'asr-server.log').open('wb'))
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            server = subprocess.Popen([str(binary), 'serve', *map(str, models), '--host', '127.0.0.1',
                                       '--port', str(port), '--device', 'gpu'], stdout=log, stderr=log)
            stack.callback(stop_process, server)
            url = f'http://127.0.0.1:{port}'
            def asr_ready():
                assert server.poll() is None
                try:
                    return SpeechCppASR(url, timeout=1).recognizers()
                except ASRError:
                    return None
            recognizers = wait_for(asr_ready, timeout=30, code='asr_not_ready')
            tts = SpeechServer(SimpleNamespace(model=qwen, speech_binary=str(binary), output=tmp_path,
                                               device='Vulkan0', seed=42))
            stack.callback(tts.stop)
            tts.start()
            references = []
            for text in TEXTS:
                frames = list(SpeechCppTTS(tts.url).synthesize_stream(text, 'ryan', 'en', CancelToken()))
                assert frames and len({f.sample_rate for f in frames}) == 1
                samples = np.frombuffer(b''.join(f.pcm for f in frames), dtype='<i2').astype(np.float32)
                samples = soxr.resample(samples, frames[0].sample_rate, 48000)
                references.append(np.clip(np.rint(samples), -32768, 32767).astype('<i2').tobytes())
            # Reference generation also warms the same model; report that boundary explicitly.
            choices = normalize_settings({'base_url': url, 'model': recognizers[0].id})
            choices['mic']['endpoint'] = endpoint_dict(next(row['endpoint'] for row in enumerate_endpoints('mic')
                                                           if row['endpoint'].name == 'vrct.native.caption.source'))
            state = initial_state(tmp_path)
            config_path = state / 'config.json'
            config = json.loads(config_path.read_text())
            languages = {str(tab): {str(slot): {'language': 'Japanese', 'country': 'Japan', 'enable': slot == 1}
                                    for slot in range(1, 4)} for tab in range(1, 6)}
            targets = {str(tab): {str(slot): {'language': 'English', 'country': 'United States', 'enable': slot == 1}
                                  for slot in range(1, 4)} for tab in range(1, 6)}
            config.update(REALTIME_ASR_SETTINGS=choices, LMSTUDIO_URL=translation.url,
                          SELECTED_TRANSLATION_ENGINES={str(tab): 'LMStudio' for tab in range(1, 6)},
                          SELECTED_YOUR_LANGUAGES=languages, SELECTED_TARGET_LANGUAGES=targets,
                          SEND_MESSAGE_TO_VRC=True, SEND_ONLY_TRANSLATED_MESSAGES=False,
                          OSC_PORT=osc.getsockname()[1])
            config_path.write_text(json.dumps(config))
            with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state),
                                                  'VRCT_VOICE_TRACE': str(trace.resolve())}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.assert_rendered()
                toggle = ui.evaluate("return [...document.querySelectorAll('[class*=switch_container]')].find(e => e.querySelector('p')?.textContent === 'Translation')")
                ui.element_command(toggle, 'click')
                ui.wait("return [...document.querySelectorAll('[class*=switch_container]')].some(e => e.querySelector('p')?.textContent === 'Translation' && e.className.includes('is_active'))")
                open_voice(ui)
                ui.select('Audio route', 'managed')
                ui.select('Realtime microphone speech', 'translated')
                ui.select('Direct input while translating', direct_policy)
                ui.fill('Other languages server (Qwen3-TTS)', tts.url)
                ui.click_text('button', 'Save voice settings')
                wait_for(lambda: json.loads(config_path.read_text()).get('VOICE_SETTINGS', {}).get('mic_mode') == 'translated')
                wait_for(lambda: gate.inspect_pair()['direct']['muted'] == (direct_policy == 'suppress'))
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Muted (confirmed)')")
                ui.click_text('button', 'Resume voice')
                wait_for(lambda: not gate.inspect()['muted'])
                settled(capture, time.monotonic_ns(), 'direct_input_policy_mismatch', **direct)
                ui.click_text('p', 'Go Back')
                open_captions(ui)
                ui.click_text('button', 'Start microphone captions')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Captions running')")
                # Existing configuration navigation pauses translation. Return
                # to the main view and observe its restoration before input.
                ui.click_text('p', 'Go Back')
                ui.wait("return [...document.querySelectorAll('[class*=switch_container]')].some(e => e.querySelector('p')?.textContent === 'Translation' && e.className.includes('is_active'))")
                recording = Capture(SOURCE, tmp_path / 'observed.pcm')
                try:
                    producer.play()
                    wait_for(lambda: len(traces()) >= 2, timeout=25, code='spoken_finals_missing')
                    assert len(traces()) == len(translation.requests) == 2
                    assert all(row['outcome'] == 'completed' for row in traces()), traces()
                    settled(capture, time.monotonic_ns(), 'completed_speech_route_mismatch', **direct)
                finally:
                    observation = recording.close()
                assert observation['valid'], observation
                observed_pcm = (tmp_path / 'observed.pcm').read_bytes()
                matches = [compare_pcm(ref, observed_pcm, 48000) for ref in references]
                assert all(match['verdict'] == 'pass' and match['occurrences'] == 1 for match in matches), matches
                # Both original and translated text must be in each single OSC
                # datagram; a partial, duplicate or untranslated send fails.
                rows = ui.evaluate("return [...document.querySelectorAll('#log_container > div')].filter(e => e.querySelector('[class*=category]')?.textContent === 'Sent').map(e => [...e.querySelectorAll('[class*=message_main],[class*=message_second]')].map(p => p.textContent));")
                assert len(rows) == 2 and all(len(row) == 2 and all(row) for row in rows), rows
                from pythonosc.osc_packet import OscPacket
                messages = []
                while True:
                    try:
                        messages.extend(t.message for t in OscPacket(osc.recv(65536)).messages)
                    except BlockingIOError:
                        break
                sent = [message.params[0] for message in messages if message.address == '/chatbox/input']
                assert len(sent) == 2 and all(sum(all(part in text for part in row) for text in sent) == 1 for row in rows), (rows, sent)
                ui.assert_rendered()
                tone_coverage = []
                if direct_policy == 'mix':
                    for match, ref in zip(matches, references):
                        start = round(match['matches'][0]['offset_seconds'] * 48000) * 2
                        observer = ToneObservation()
                        observer.feed(observed_pcm[start:start + len(ref)], time.monotonic_ns())
                        stats = observer.snapshot()
                        fraction = stats['detected_frames']['440'] / stats['frames']
                        tone_coverage.append(fraction)
                        assert fraction >= .95, stats
                measured = []
                for row in traces():
                    assert row['first_write_ns'] is not None
                    item = {'final_receipt_to_first_write_ms': (row['first_write_ns'] - row['started_ns']) / 1e6}
                    # The continuously mixed tone makes a nonzero read unsuitable
                    # for measuring TTS onset. Never report that as TTS latency.
                    if direct_policy == 'suppress':
                        with capture.lock:
                            first = next((stamp for stamp, _, nonzero in capture.history
                                          if stamp >= row['first_write_ns'] and nonzero), None)
                        assert first is not None
                        item['final_receipt_to_private_read_ms'] = (first - row['started_ns']) / 1e6
                    measured.append(item)
                if direct_policy == 'suppress':
                    translation.translations = ['This is a longer sentence for stopping the translated speech. ' * 12]
                    before = time.monotonic_ns()
                    producer.play()
                    def active_audio():
                        with capture.lock:
                            return any(stamp > before and nonzero for stamp, _, nonzero in capture.history)
                    wait_for(active_audio, timeout=15, code='stop_trial_no_audio')
                stop_call = time.monotonic_ns()
                ui.click_text('button', 'Stop microphone captions')
                silent = settled(capture, stop_call, 'mic_stop_route_mismatch', **direct)
                wait_for(lambda: not any(name.startswith('vrct.asr.capture.') for name in nodes()))
                count = len(translation.requests)
                assert producer.play().wait(15)
                settled(capture, time.monotonic_ns(), 'stopped_input_route_mismatch', **direct)
                assert len(translation.requests) == count
                if direct_policy == 'suppress':
                    assert any(row['outcome'] == 'cancelled' for row in traces()[2:]), traces()
                else:
                    assert len(traces()) == 2
                ui.close_app()
            assert gate.inspect()['muted']
            with NativeWebDriver(tmp_path / 'restart', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                open_voice(ui)
                assert ui.evaluate('return arguments[0].value', ui.control('Realtime microphone speech')) == 'translated'
                assert gate.inspect()['muted']
                assert not any(name.startswith('vrct.asr.capture.') for name in nodes())
                ui.close_app()
            report.update(status='passed', warm=True, measurements=measured, matches=matches,
                          stop_call_to_silent_private_read_ms=((silent - stop_call) / 1e6 if direct_policy == 'suppress' else None),
                          stop_during_speech=direct_policy == 'suppress',
                          original_and_translated_osc_once=True, osc_messages=2,
                          direct_tone_coverage_during_speech=tone_coverage,
                          route_confirmation_ms=2000,
                          silence_confirmation_ms=2000 if direct_policy == 'suppress' else None,
                          restart_capture_off_and_muted=True,
                          capture=capture.snapshot(), trace=traces())
    finally:
        (tmp_path / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
