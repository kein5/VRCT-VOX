"""With the user at the PC: the frozen sidecar on the built-in microphone. No audio is kept.

1. Classic path (Whisper tiny): the message while Windows' question is unanswered, then recognition.
2. Realtime captions (Qwen3-ASR, device auto) on the microphone.
3. RVC on the same microphone while the captions keep running.
"""
import collections
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRATCH))
import numpy as np  # noqa: E402
import win_e2e as e  # noqa: E402
import win_frozen  # noqa: E402

ROOT = win_frozen.ROOT
win_frozen.FROZEN = ROOT / 'build/frozen-mic2/vrct-vox-sidecar-x86_64-pc-windows-msvc.exe'
OUT = ROOT / 'build/model-test/win-mic-full'
BASE = next((p for p in (ROOT / 'build/model-test').iterdir() if (p / 'vc_runtimes').is_dir()), None)
M = ROOT / 'build/model-test/win-voice'
TTS_MODEL = str(M / 'irodori-v41-q8/Irodori-TTS-866M-MF-v4.1-Q8_0.gguf')
ASR_MODEL = str(M / 'qwen3-asr-06b-q8/Qwen3-ASR-0.6B-Q8_0.gguf')
VAD_MODEL = str(M / 'silero-vad-v62/silero-vad-309K-v6.2-F32.gguf')
SENTENCE = '今日はとても良い天気ですね。一緒に散歩に行きましょう。'
LABEL = os.environ.get('VOX_MIC_LABEL') or 'Surface'
CLASSIC = '/run/transcription_send_mic_message'
CAPTION = '/run/realtime_caption'


def say(text):
    print(f'\n>>>>> {text}\n', flush=True)


def question():
    return subprocess.run(['powershell', '-NoProfile', '-Command', '(Get-Process PickerHost -ErrorAction SilentlyContinue).MainWindowTitle'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace').stdout.strip()


def wait_question_closed(app, limit=600):
    """An unanswered question must never outlive the sidecar: that would count as a refusal."""
    started = time.monotonic()
    while time.monotonic() - started < limit:
        title = question()
        if not title:
            return time.monotonic() - started
        app.pump(2)
    return None


def collect(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.pump(.1)


def finals(events):
    texts = []
    for event in events:
        answer = event.get('result') or {}
        if event.get('endpoint') == CLASSIC:
            texts.append(((answer.get('original') or {}).get('message')) or answer.get('text') or str(answer)[:80])
        elif event.get('endpoint') == CAPTION and (answer.get('state') in ('final', 'finalized', 'done') or answer.get('is_final')):
            texts.append(answer.get('text'))
    return [t for t in texts if t]


def noted(events):
    return [(event.get('endpoint'), event.get('status'), str(event.get('result'))[:220]) for event in events
            if (event.get('status') or 200) >= 400 or 'error' in str(event.get('endpoint')) or 'AUDIO_OPEN' in str(event)]


def choose_mic(app):
    app.call('/set/disable/auto_mic_select')
    hosts = e.result(app.call('/get/data/selectable_mic_host_list'))
    host = next((h for h in hosts if 'WASAPI' in str(h)), None)
    if host:
        app.call('/set/data/selected_mic_host', host)
    devices = e.result(app.call('/get/data/selectable_mic_device_list'))
    name = next((d for d in devices if LABEL in str(d)), None)
    if not name:
        app.record('classic: microphone chosen', False, json.dumps([hosts, devices], ensure_ascii=False)[:300])
        return
    app.call('/set/data/selected_mic_device', name)
    app.record('classic: microphone chosen', True, f'{host} / {name}')


def classic(app):
    app.call('/set/data/selected_transcription_engine', 'Whisper')
    app.call('/set/data/selected_whisper_weight_type', 'tiny')
    settings = e.result(app.call('/get/data/realtime_asr_settings'))
    settings['server'] = 'external'  # The saved settings of an earlier run would pick the realtime path.
    app.record('classic: path selected', app.call('/set/data/realtime_asr_settings', settings)['status'] == 200, settings['server'])
    choose_mic(app)
    if 'low' in sys.argv:
        event = app.call('/set/data/mic_threshold', 40)
        app.record('classic: threshold lowered', event['status'] == 200, event.get('result'))
    mark = len(app.seen)
    started = time.monotonic()
    say('開始しています。')
    app.send('/set/enable/transcription_send')
    asked = None
    while time.monotonic() - started < (30 if asked else 12):
        app.pump(.5)
        title = question()
        if title and asked is None:
            asked = title
            print(f'question after {time.monotonic() - started:.0f}s: {title}', flush=True)
        if noted(app.seen[mark:]):
            break
    message = noted(app.seen[mark:])
    app.record('classic: told while the question is open', bool(message) or asked is None,
               f'{time.monotonic() - started:.1f}s {message[:2]}')
    closed = wait_question_closed(app)
    app.record('classic: question answered', closed is not None, f'waited {closed}s, question={asked}')
    collect(app, 3)
    app.send('/set/disable/transcription_send')
    collect(app, 3)
    mark = len(app.seen)
    say(f'話してください（1 文ごとに少し間をあけて）: {SENTENCE}')
    app.send('/set/enable/transcription_send')
    collect(app, 30)
    say('（従来の経路の確認が終わりました。そのまま読み続けてください）')
    app.send('/set/disable/transcription_send')
    collect(app, 3)
    texts = finals(app.seen[mark:])
    app.record('classic: recognized the microphone', bool(texts), f'{len(texts)} {texts[:6]}')
    print('classic events', collections.Counter(str(ev.get('endpoint')) for ev in app.seen[mark:]).most_common(8), flush=True)
    for name in ('/get/data/mic_threshold', '/get/data/mic_automatic_threshold', '/get/data/selected_mic_device', '/get/data/selected_mic_host'):
        print(name, app.call(name).get('result'), flush=True)
    if noted(app.seen[mark:]):
        print('classic notes', noted(app.seen[mark:])[:3], flush=True)


def levels(app):
    """The energy the classic path compares with its threshold. Only the numbers are kept."""
    mark = len(app.seen)
    say(f'話してください（音量を測ります）: {SENTENCE}')
    app.call('/set/enable/check_mic_threshold', timeout=20)
    collect(app, 12)
    app.call('/set/disable/check_mic_threshold', timeout=20)
    values = [float(ev['result']) for ev in app.seen[mark:] if ev.get('endpoint') == '/run/check_mic_volume' and isinstance(ev.get('result'), (int, float))]
    if values:
        ordered = sorted(values)
        print(f'mic energy: n={len(values)} median={ordered[len(values) // 2]:.0f} p95={ordered[int(len(values) * .95)]:.0f} max={ordered[-1]:.0f}', flush=True)
    else:
        print('mic energy: no numbers', collections.Counter(str(ev.get('endpoint')) for ev in app.seen[mark:]).most_common(5), flush=True)


def captions(app):
    profiles = dict(japanese=dict(model=TTS_MODEL, vad_model='', voice_file='', device='auto', low_latency=False),
                    multilingual=dict(model='', vad_model='', voice_file='', device='auto', low_latency=False),
                    asr=dict(model=ASR_MODEL, vad_model=VAD_MODEL, voice_file='', device='auto', low_latency=False))
    app.call('/set/data/speech_server_settings', dict(version=1, profiles=profiles))
    settings = e.result(app.call('/get/data/realtime_asr_settings'))
    endpoints = e.result(app.call('/get/data/realtime_asr_endpoints', {'source': 'mic'}))
    target = next(row for row in endpoints['endpoints'] if LABEL in row['label'])
    settings['server'] = 'bundled'
    settings['mic'].update(endpoint=target['endpoint'], follow_default=False, language='auto')
    app.record('captions: settings', app.call('/set/data/realtime_asr_settings', settings)['status'] == 200, target['label'])
    started = time.monotonic()
    event = app.call('/set/enable/transcription_send', timeout=180)
    app.record('captions: started on the microphone', event['status'] == 200 and event.get('result') is True,
               f"{time.monotonic() - started:.1f}s {event['status']} {str(event.get('result'))[:200]}")
    if event['status'] != 200:
        return False
    mark = len(app.seen)
    say(f'話してください（1 文ごとに少し間をあけて）: {SENTENCE}')
    collect(app, 30)
    texts = finals(app.seen[mark:])
    app.record('captions: recognized the microphone', bool(texts), f'{len(texts)} {texts[:6]}')
    print('caption events', collections.Counter(str(ev.get('endpoint')) for ev in app.seen[mark:]).most_common(8), flush=True)
    return True


def rvc(app):
    runtime, model, index = str(BASE / 'vc_runtimes/rvc'), str(BASE / 'model.pth'), str(BASE / 'model.index')
    app.call('/set/data/direct_voice_settings', dict(mode='converted', runtime='', reference='', engine='rvc', rvc_runtime=runtime,
                                                     rvc_model=model, rvc_index=index, rvc_pitch=0, rvc_index_rate=.5))
    voice = e.result(app.call('/get/data/voice_settings'))
    voice.update(output_device=e.SPEAKERS, routing='external', mode='off')
    app.call('/set/data/voice_settings', voice)
    sources = e.result(app.call('/get/data/direct_voice_sources'))
    target = next(s['id'] for s in sources['sources'] if LABEL in s['label'])
    app.call('/run/resume_voice', timeout=20)
    started = time.monotonic()
    say('RVC を準備しています。そのまま読み続けてください。')
    event = app.call('/run/start_direct_voice', {'source': target, 'mode': 'converted', 'options': dict(
        engine='rvc', runtime=runtime, model=model, index=index, pitch=0, index_rate=.5)})
    app.record('rvc: accepted', event['status'] == 200, str(event.get('result'))[:120])
    state = e.wait_direct(app, lambda s: s.get('error') or s.get('conversion_verified'), 195)
    app.record('rvc: converting the real microphone', bool(state.get('conversion_verified')) and not state.get('error'),
               f"{time.monotonic() - started:.1f}s state={state.get('conversion_state')} error={state.get('error')}")
    if state.get('error'):
        return
    mark = len(app.seen)
    say(f'話してください（RVC と字幕を同時に確かめています）: {SENTENCE}')
    with e.Recorder('Steam Streaming Speakers') as recorder:
        collect(app, 25)
        samples = recorder.audio().astype(np.int32)
    state = e.result(app.call('/get/data/direct_voice_state'))
    peak = int(np.abs(samples).max()) if len(samples) else 0
    del samples
    app.record('rvc: still converting', bool(state.get('conversion_verified')) and not state.get('error'),
               f"state={state.get('conversion_state')} blocks={state.get('converted_blocks')} error={state.get('error')}")
    app.record('rvc: output reached the device', peak > 0, f'peak {peak}')
    texts = finals(app.seen[mark:])
    app.record('captions: kept working next to rvc', bool(texts), f'{len(texts)} {texts[:6]}')
    app.call('/run/stop_direct_voice')
    stopped = e.wait_direct(app, lambda s: not s.get('requested') and not s.get('stopping'), 15)
    app.record('rvc: stopped', not stopped.get('active'), f"error={stopped.get('error')}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    e.OUT = OUT
    link = win_frozen.FROZEN.parent / 'weights'
    if not link.exists():
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(ROOT / 'src-python/weights')], capture_output=True)
    print('existing question:', repr(question()), flush=True)
    app = win_frozen.FrozenBackend(OUT)
    try:
        init = app.start()
        your = init['/get/data/selected_your_languages']
        your[init['/get/data/selected_tab_no']]['1'].update(language='Japanese', country='Japan', enable=True)
        app.call('/set/data/selected_your_languages', your)
        app.call('/set/disable/translation')
        classic(app)
        if 'low' in sys.argv:
            pass
        elif 'classic' in sys.argv:
            levels(app)
        elif captions(app):
            if 'norvc' not in sys.argv:
                rvc(app)
            app.call('/set/disable/transcription_send', timeout=30)
    except Exception as error:  # noqa: BLE001
        app.record('script', False, repr(error))
    finally:
        closed = wait_question_closed(app) if question() else 0
        print('question closed before exit:', closed is not None, flush=True)
        say('話すのをやめてください。試験は終わりました。')
        print('sidecar stderr tracebacks:', (OUT / 'stderr.log').read_text(encoding='utf-8', errors='replace').count('Traceback'), flush=True)
        app.close()
        try:
            (OUT / 'stdout.log').unlink()  # It holds what was recognized.
        except OSError as error:
            print('stdout.log stays:', error, flush=True)


if __name__ == '__main__':
    main()
