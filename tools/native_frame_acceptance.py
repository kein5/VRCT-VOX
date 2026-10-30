"""Opt-in prepared-host GUI/managed-source acceptance with a real VRChat consumer.

Requires an initial muted managed route, a ready local Irodori server, the
caller-prepared private VRChat instance and Frame playback sink. Creates only
its own app/capture/monitor processes; host route setup/restore remains the
caller responsibility. No VRChat internal replay, HMD input or acoustic claims.
Fcitx/Mozc is a separate assertion and can be explicitly excluded with --skip-ime.
"""
import argparse
import ast
import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src-python'), str(ROOT / 'tests/platform')]
from native_webdriver import NativeWebDriver
from test_native_quick_chat import xdo, window_for, sidecars
from tools.voice_acceptance import wait_for
from tools.voice_b_poc import ToneCapture
from tools.managed_vrchat_probe import require_continuous_capture
from tools.vrchat_gui_probe import Capture
from tools.vrchat_audio_probe import compare_pcm, silence_pcm
from tools.voice_route_watch import RouteWatch
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
from models.tts.speechcpp_tts import SpeechCppTTS, CancelToken
from tools.acceptance_lifecycle import finalize_acceptance

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--server', required=True)
    parser.add_argument('--quick-only', action='store_true')
    parser.add_argument('--ime-socket')
    parser.add_argument('--skip-ime', action='store_true')
    parser.add_argument('--vrchat-pid', type=int, required=True)
    parser.add_argument('--vrchat-window', required=True)
    return parser.parse_args()

def run(args):
    OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=False)
    OUT.chmod(448)
    report = {'status': 'running', 'cases': [], 'vrchat_pid': args.vrchat_pid, 'boundary': 'actual GUI -> actual model -> managed source connected to real VRChat', 'vrchat_internal_replay': False, 'hmd_input': False, 'physical_hearing': False, 'route_watch_scope': 'received PipeWire changes; no sync heartbeat, changes may coalesce'}

    def save():
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))

    def note(name, **details):
        report['cases'].append({'name': name, 'status': 'observed_pending_final_validation', **details})
        save()
        print(name, flush=True)
    state = OUT / 'state'
    state.mkdir()
    config = {'AUTO_DOWNLOAD_MODELS': False, 'ENABLE_TELEMETRY': False, 'AUTO_MIC_SELECT': False, 'AUTO_SPEAKER_SELECT': False, 'SEND_MESSAGE_TO_VRC': False, 'VRC_MIC_MUTE_SYNC': False, 'OSC_IP_ADDRESS': '127.0.0.2', 'WEBSOCKET_SERVER': False, 'UI_LANGUAGE': 'en', 'AUTO_CLEAR_MESSAGE_BOX': True, 'HOTKEYS': {'open_quick_chat': ['Ctrl', 'Shift', 'Alt', 'F9']}, 'VOICE_SETTINGS': {'mode': 'off', 'routing': 'external', 'japanese_url': args.server, 'japanese_seed': '3', 'japanese_instructions': ''}}
    (state / 'config.json').write_text(json.dumps(config))
    registry = OUT / 'ui/config/openvr'
    registry.mkdir(parents=True)
    shutil.copyfile(Path.home() / '.config/openvr/openvrpaths.vrpath', registry / 'openvrpaths.vrpath')
    os.environ.update(VRCT_TEST_APP=str(args.app.resolve()), VRCT_TEST_APPIMAGE='1')
    SHORT = 'これはVRCTの音声テストです。'
    LONG = 'これは読み上げを途中で停止する試験です。文章が続いている間に停止します。' * 4
    gate = PipeWireGate()
    capture = None
    watch = None
    capture_result = None
    gate_identity = gate.inspect()['identity']
    ime_before = subprocess.check_output(['fcitx5-remote'], text=True).strip()

    def backend_status():
        p = state / 'logs/process.log'
        if not p.exists():
            return None
        with p.open('rb') as f:
            f.seek(max(0, p.stat().st_size - 160000))
            data = f.read().decode(errors='replace')
        for line in reversed(data.splitlines()):
            if "'endpoint': '/get/data/voice_status'" not in line:
                continue
            d = ast.literal_eval(line.split(' - INFO - ', 1)[1])['result']
            if time.monotonic_ns() - int(d['observation_id']) > 4000000000.0:
                return None
            return d
        return None
    try:
        assert gate.inspect()['muted'] is True
        ref = lambda: b''.join((f.pcm for f in SpeechCppTTS(args.server).synthesize_stream(SHORT, 'none', 'ja', CancelToken(), seed=3)))
        reference = ref()
        assert reference and ref() == reference, 'reference_not_deterministic'
        (OUT / 'reference.pcm').write_bytes(reference)
        report['reference_seconds'] = len(reference) / 96000
        with ExitStack() as stack:
            ui = stack.enter_context(NativeWebDriver(OUT / 'ui', {'VRCT_CONFIG_DIR': str(state), 'GDK_BACKEND': 'x11'}))
            app_env = ui.app_process.environ()
            report['input_environment'] = {k: app_env.get(k) for k in ('GTK_IM_MODULE', 'GTK_IM_MODULE_FILE', 'XMODIFIERS', 'LC_ALL', 'LC_CTYPE')}
            ui.wait("return document.querySelector('textarea[class*=message_box_input_area]') !== null")
            ui.open_route_settings()
            ui.select('Audio route', 'managed')
            ui.click_text('button', 'Save audio route')
            wait_for(lambda: json.loads((state / 'config.json').read_text()).get('VOICE_SETTINGS', {}).get('routing') == 'managed')
            ui.open_voice_settings()
            ui.select('Chat voice', 'original')
            ui.click_text('button', 'Save voice settings')
            wait_for(lambda: json.loads((state / 'config.json').read_text())['VOICE_SETTINGS']['mode'] == 'original')
            ui.open_route_settings()
            ui.click_text('button', 'Resume voice')
            ui.wait("return [...document.querySelectorAll('[role=status]')].some(e=>e.textContent==='Voice enabled (confirmed)')")
            ui.close_settings()
            if ui.evaluate("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked')") == 'false':
                ui.click('[role=switch][aria-label=TTS]')
            ui.wait("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked')==='true'")
            main = ui.command('GET', '/window')
            main_xid, = window_for(ui.app_process.pid, 'VRCT-VOX')
            before_sidecars = sidecars(ui)
            assert len(before_sidecars) == 1
            observer = ToneCapture(stack, SOURCE)
            capture = Capture(SOURCE, OUT / 'continuous-source.pcm')
            watch = RouteWatch(SOURCE, 'vrlink-sink', args.vrchat_pid, OUT / 'route-events.jsonl')
            started = time.monotonic()

            def healthy():
                watch.check()
                s = observer.snapshot()
                require_continuous_capture(s)
                assert observer.process.poll() is None and time.monotonic_ns() - s['last_read_ns'] < 300000000.0, 'capture_not_live'
                assert capture.process.poll() is None and capture.thread.is_alive() and (not capture.error), 'raw_capture_not_live'
                assert ui.app_process.is_running() and Path('/proc/' + str(args.vrchat_pid)).exists()
                assert sidecars(ui) == before_sidecars

            def wait_checked(fn, timeout=20):
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    healthy()
                    value = fn()
                    if value:
                        return value
                    time.sleep(0.05)
                raise RuntimeError('checked_condition_timeout')

            def observe_seconds(seconds):
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    healthy()
                    time.sleep(0.05)

            def status():
                return wait_checked(backend_status, 5)

            def quiet():
                return wait_checked(lambda: observer.settled(time.monotonic_ns() - int(4000000000.0), silent=True, duration_ms=2000), 10)

            def send(text):
                ui.command('POST', '/window', {'handle': main})
                xdo('windowactivate', '--sync', main_xid)
                field = ui.command('POST', '/element', {'using': 'css selector', 'value': 'textarea[class*=message_box_input_area]'})
                ui.element_command(field, 'clear')
                ui.element_command(field, 'value', {'text': text})
                assert ui.evaluate('return arguments[0].value', field) == text, 'native_text_entry_mismatch'
                before = status()
                start = time.monotonic_ns()
                ui.click('[class*=message_send_button]')
                ui.wait("return document.querySelector('textarea[class*=message_box_input_area]').value===''")
                return (before, start)

            def completed(before):
                after = wait_checked(lambda: s if (s := backend_status()) and (not s['active']) and (not s['queued']) and (s['completed'] > before['completed']) else None, 30)
                assert after['accepted'] == before['accepted'] + 1 and after['completed'] == before['completed'] + 1, after
                assert all((after[k] == before[k] for k in ('errors', 'cancelled', 'duplicates', 'dropped'))), after
                return after

            def positive(name):
                quiet()
                path = OUT / (name + '.pcm')
                c = Capture(SOURCE, path)
                try:
                    observe_seconds(0.5)
                    before, start = send(SHORT)
                    after = completed(before)
                    quiet()
                    observe_seconds(0.5)
                finally:
                    validation = c.close()
                assert validation['valid'], validation
                audio = compare_pcm(reference, path.read_bytes(), 48000)
                assert audio['verdict'] == 'pass' and audio['occurrences'] == 1, audio
                note(name, backend_before=before, backend_after=after, audio=audio, capture=validation)

            def silence(name, action):
                quiet()
                path = OUT / (name + '.pcm')
                c = Capture(SOURCE, path)
                try:
                    before = status()
                    action()
                    observe_seconds(3)
                    after = status()
                finally:
                    validation = c.close()
                assert validation['valid'], validation
                audio = silence_pcm(path.read_bytes(), 48000, minimum_seconds=3)
                assert audio['verdict'] == 'pass', audio
                assert after['accepted'] == before['accepted'] and after['completed'] == before['completed'] and (after['errors'] == before['errors']) and (not after['active']) and (not after['queued']), after
                note(name, backend_before=before, backend_after=after, audio=audio, capture=validation)
            if not args.quick_only:
                positive('main_gui_exactly_once')
                for name in ('stop', 'held_mute'):
                    nonzero_before = observer.snapshot()['nonzero_frames']
                    before, start = send(LONG)
                    wait_checked(lambda: observer.snapshot()['nonzero_frames'] > nonzero_before)
                    ui.open_voice_settings() if name == 'stop' else ui.open_route_settings()
                    stop = time.monotonic_ns()
                    ui.click_text('button', 'Stop playback and clear queue' if name == 'stop' else 'Mute until resumed')
                    ended = wait_checked(lambda: observer.settled(stop, silent=True, duration_ms=2000), 8)
                    after = wait_checked(lambda: s if (s := backend_status()) and (not s['active']) and (not s['queued']) else None, 8)
                    assert after['cancelled'] == before['cancelled'] + 1 and after['errors'] == before['errors'], after
                    if name == 'held_mute':
                        assert gate.inspect()['muted'] is True
                    note(name, call_to_continuous_silence_ms=(ended - stop) / 1000000.0, backend_after=after)
                    ui.close_settings()
                silence('held_mute_new_message', lambda: send(SHORT))
                ui.open_route_settings()
                ui.click_text('button', 'Resume voice')
                wait_checked(lambda: not gate.inspect()['muted'])
                ui.close_settings()
                ui.click('[role=switch][aria-label=TTS]')
                ui.wait("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked')==='false'")
                silence('tts_off_new_message', lambda: send(SHORT))
                silence('tts_on_has_no_stale_replay', lambda: ui.click('[role=switch][aria-label=TTS]'))
                positive('resume_exactly_once')
            xdo('windowminimize', main_xid)
            xdo('windowactivate', '--sync', args.vrchat_window)
            xdo('key', '--clearmodifiers', 'ctrl+alt+shift+F9')
            wait_checked(lambda: window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat'))
            chat, = [h for h in ui.command('GET', '/window/handles') if h != main]
            ui.command('POST', '/window', {'handle': chat})
            ui.wait("return document.hasFocus()&&document.activeElement?.tagName==='TEXTAREA'")
            ui.fill('Message', 'quick chat draft')
            for index in range(3):
                xdo('key', 'Escape')
                wait_checked(lambda: not window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat'))
                focus_samples = []
                for _ in range(20):
                    focus_samples.append({'active': xdo('getactivewindow'), 'focus': xdo('getwindowfocus')})
                    if focus_samples[-1]['active'] == args.vrchat_window:
                        break
                    time.sleep(0.1)
                report['last_escape_focus_samples'] = focus_samples
                assert focus_samples[-1]['active'] == args.vrchat_window, 'Esc_did_not_return_to_VRChat'
                assert not window_for(ui.app_process.pid, 'VRCT-VOX'), 'main_restored_unexpectedly'
                note('quick_chat_escape_returns_to_game_' + str(index), active_window=xdo('getactivewindow'), input_focus=xdo('getwindowfocus'))
                xdo('key', '--clearmodifiers', 'ctrl+alt+shift+F9')
                ui.wait("return document.hasFocus()&&document.activeElement?.tagName==='TEXTAREA'")
                assert ui.evaluate('return document.querySelector("textarea").value') == 'quick chat draft'
            if not args.skip_ime:
                ui.element_command(ui.control('Message'), 'clear')
                chat_xid, = window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat')
                xdo('mousemove', '--window', chat_xid, 100, 80)
                xdo('click', 1)
                ui.wait("return document.hasFocus() && document.activeElement?.tagName==='TEXTAREA'")
                ui.evaluate("window.__imeEvents=[]; for(const t of ['compositionstart','compositionupdate','compositionend','keydown']) document.querySelector('textarea').addEventListener(t,e=>window.__imeEvents.push({type:e.type,key:e.key,data:e.data,isComposing:e.isComposing,keyCode:e.keyCode})); return true")
                before = status()
                subprocess.run(['fcitx5-remote', '-o'], check=True)
                report['ime_context_before_typing'] = subprocess.check_output(['gdbus', 'call', '--session', '--dest', 'org.fcitx.Fcitx5', '--object-path', '/controller', '--method', 'org.fcitx.Fcitx.Controller1.DebugInfo'], text=True)
                wait_checked(lambda: subprocess.check_output(['fcitx5-remote'], text=True).strip() == '2', 3)

                def ime_key(code, xkey):
                    if args.ime_socket:
                        subprocess.run(['ydotool', 'key', f'{code}:1', f'{code}:0'], env={**os.environ, 'YDOTOOL_SOCKET': args.ime_socket}, check=True, timeout=5)
                    else:
                        xdo('key', xkey)
                if args.ime_socket:
                    subprocess.run(['ydotool', 'type', '--key-delay', '100', 'nihongo'], env={**os.environ, 'YDOTOOL_SOCKET': args.ime_socket}, check=True, timeout=10)
                else:
                    xdo('type', '--clearmodifiers', '--delay', '100', 'nihongo')
                ime_key(57, 'space')
                observe_seconds(0.5)
                commit_key_started_ns = time.monotonic_ns()
                ime_key(28, 'Return')
                commit_key_finished_ns = time.monotonic_ns()
                observe_seconds(2)
                text = ui.evaluate('return document.querySelector("textarea").value')
                events = ui.evaluate('return window.__imeEvents')
                (OUT / 'ime-events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2))
                committed = wait_checked(lambda: s if (s := backend_status()) and
                                         int(s['observation_id']) > commit_key_finished_ns else None, 5)
                (OUT / 'ime-commit.json').write_text(json.dumps({
                    'text': text, 'backend_before': before,
                    'backend_after_commit': committed, 'events': events,
                    'commit_key_started_ns': commit_key_started_ns,
                    'commit_key_finished_ns': commit_key_finished_ns,
                    'input': 'native romaji keys, Space, Enter; no Unicode injection',
                }, ensure_ascii=False, indent=2))
                # GTK may use an external preedit window. In that mode WebKit
                # receives keyCode 229 without DOM composition events. Require
                # both IME evidence and the actual converted, unsent text.
                assert any(e['type'].startswith('composition') or e.get('keyCode') == 229
                           for e in events), 'real_IME_input_not_observed'
                assert text == '日本語' and committed['accepted'] == before['accepted'], 'IME_commit_sent_or_not_converted'
                ime_key(28, 'Return')
                ui.wait("return document.querySelector('textarea').value===''")
                after = completed(before)
                quiet()
                note('real_fcitx_mozc_commit_then_send', text=text, backend_before=before, backend_after=after)
                subprocess.run(['fcitx5-remote', '-c'], check=True)
                xdo('key', 'Escape')
                wait_checked(lambda: xdo('getactivewindow') == args.vrchat_window, 3)
            else:
                report['ime_test'] = 'not validated; separate attempts could not activate the input context'
                xdo('key', 'Escape')
                wait_checked(lambda: xdo('getactivewindow') == args.vrchat_window, 3)
            ui.command('POST', '/window', {'handle': main})
            xdo('windowactivate', '--sync', main_xid)
            count = 0
            while time.monotonic() - started < args.seconds:
                positive('stability_' + str(count))
                count += 1
                until = min(started + args.seconds, time.monotonic() + 25)
                while time.monotonic() < until:
                    healthy()
                    time.sleep(0.1)
            report['observed_seconds'] = time.monotonic() - started
            report['stability_iterations'] = count
            report['observer'] = observer.snapshot()
            healthy()
            capture_result = capture.close()
            capture = None
            assert capture_result['valid'], capture_result
            report['continuous_capture'] = capture_result
            report['route_final'] = watch.finish()
            watch = None
            ui.assert_rendered()
            ui.close_app()
            assert gate.inspect()['muted'] is True
            report['owned_app_exited_source_muted'] = True
        report['status'] = 'verified' if args.seconds >= 600 else 'smoke_verified'
    except BaseException as exc:
        report.update(status='failed', error=repr(exc))
        raise
    finally:

        def mute_owned_route():
            gate.set_muted(True, gate_identity)
            observed = gate.inspect()
            assert observed['identity'] == gate_identity and observed['muted'] is True
            return observed

        def close_capture():
            if capture:
                report['continuous_capture'] = capture.close()
            return report.get('continuous_capture')

        def restore_ime():
            subprocess.run(['fcitx5-remote', '-o' if ime_before == '2' else '-c'], check=True)
            return {'requested_state': ime_before}
        finalize_acceptance(report, [('mute', mute_owned_route), ('capture', close_capture), ('watch', lambda: watch.close() if watch else None), ('ime', restore_ime)], save, error=sys.exc_info()[1])
        print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, ensure_ascii=False), flush=True)
if __name__ == '__main__':
    run(parse_args())
