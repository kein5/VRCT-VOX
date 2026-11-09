"""Windows voice end to end through the real sidecar, real models and real WASAPI devices.

No microphone or audible speaker: voice goes to Steam's silent virtual outputs and
is read back through their WASAPI loopback.
"""
import json
import os
from pathlib import Path
import sys
import threading
import time
import wave

SCRATCH = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('VOX_FIELD_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(SCRATCH))
sys.path.insert(0, str(ROOT / 'src-python'))
import numpy as np  # noqa: E402
import harness  # noqa: E402

from models.audio_routing.devices_windows import WindowsOutput, enumerate_endpoints  # noqa: E402
from models.transcription.capture_windows import WindowsCapture  # noqa: E402
from models.tts.speechcpp_tts import CancelToken  # noqa: E402

OUT = ROOT / 'build/model-test/win-e2e'
M = ROOT / 'build/model-test/win-voice'
SPEAKERS = '["Windows WASAPI", "Speakers (Steam Streaming Speakers)"]'
CABLE = '["Windows WASAPI", "Speakers (Steam Streaming Microphone)"]'
TTS_MODEL = str(M / 'irodori-v41-q8/Irodori-TTS-866M-MF-v4.1-Q8_0.gguf')
ASR_MODEL = str(M / 'qwen3-asr-06b-q8/Qwen3-ASR-0.6B-Q8_0.gguf')
VAD_MODEL = str(M / 'silero-vad-v62/silero-vad-309K-v6.2-F32.gguf')
PHRASE = '今日はとても良い天気ですね。一緒に散歩に行きましょう。'


class Recorder:
    def __init__(self, label):
        self.endpoint = next(r['endpoint'] for r in enumerate_endpoints('speaker') if label in r['label'])
        self.frames, self.errors = [], []
        self.capture = WindowsCapture(self.endpoint, 'speaker', self._add, self.errors.append)

    def _add(self, frame):
        self.frames.append(frame)
        return True

    def __enter__(self):
        self.capture.start()
        return self

    def __exit__(self, *_):
        self.capture.stop()

    def audio(self):
        return np.frombuffer(b''.join(f.audio.pcm for f in self.frames), dtype='<i2')


def save(path, samples):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(48000)
        out.writeframes(samples.astype('<i2').tobytes())


def load(path):
    with wave.open(str(path), 'rb') as reader:
        return reader.readframes(reader.getnframes())


def play(device, pcm, seconds=None):
    token = CancelToken()
    output = WindowsOutput(device, 48000, 1, strict_underflow=False)
    for offset in range(0, len(pcm), 960):
        output.write(pcm[offset:offset + 960], token)
    output.close(drain=True, token=token)


def speech_window(samples, threshold=600):
    active = np.flatnonzero(np.abs(samples.astype(int)) > threshold)
    return samples[active[0]:active[-1] + 1] if len(active) else samples[:0]


def result(event):
    return (event or {}).get('result') or {}


def tts(app):
    settings = dict(version=1, profiles=dict(
        japanese=dict(model=TTS_MODEL, vad_model='', voice_file='', device='auto', low_latency=False),
        multilingual=dict(model='', vad_model='', voice_file='', device='auto', low_latency=False),
        asr=dict(model=ASR_MODEL, vad_model=VAD_MODEL, voice_file='', device='auto', low_latency=False)))
    event = app.call('/set/data/speech_server_settings', settings)
    app.record('speech server settings', event['status'] == 200, event['status'])
    voice = result(app.call('/get/data/voice_settings'))
    voice.update(mode='original', japanese_server='bundled', output_device=SPEAKERS, routing='external')
    event = app.call('/set/data/voice_settings', voice)
    app.record('voice settings', event['status'] == 200, event['status'])
    status = result(app.call('/get/data/voice_status'))
    started = time.monotonic()
    event = app.call('/run/enable_tts', {'generation': status['tts_generation']}, timeout=150)
    app.record('tts enable (bundled speech.exe)', event['status'] == 200 and result(event).get('tts_enabled') is True,
               f"{time.monotonic()-started:.1f}s {event['status']} {str(result(event))[:160]}")
    with Recorder('Steam Streaming Speakers') as recorder:
        sent = time.monotonic()
        app.send('/run/send_message_box', {'id': 'win-tts-1', 'message': PHRASE})
        first = None
        deadline = time.monotonic() + 30
        last_loud = None
        while time.monotonic() < deadline:
            app.pump(.1)
            loud = bool(recorder.frames) and np.abs(np.frombuffer(recorder.frames[-1].audio.pcm, '<i2').astype(int)).max() > 600
            if loud:
                first = first or time.monotonic()
                last_loud = time.monotonic()
            if last_loud and time.monotonic() - last_loud > 3.5:
                break
    samples = recorder.audio()
    speech = speech_window(samples)
    save(OUT / 'tts.wav', speech)
    app.record('tts audio reached the device', len(speech) > 48000,
               f'{len(speech)/48000:.2f}s peak={np.abs(speech.astype(int)).max() if len(speech) else 0} '
               f'first_audio={first-sent if first else None} errors={recorder.errors}')
    status = result(app.call('/get/data/voice_status'))
    app.record('tts status clean', not status.get('error'), str(status)[:220])
    app.call('/run/disable_tts', timeout=20)
    for _ in range(40):
        state = result(app.call('/get/data/speech_server_state'))
        if state.get('japanese', {}).get('state') == 'stopped':
            break
        time.sleep(.1)
    app.record('tts server stopped with the toggle', state.get('japanese', {}).get('state') == 'stopped',
               state.get('japanese'))


def asr(app):
    settings = result(app.call('/get/data/realtime_asr_settings'))
    endpoints = result(app.call('/get/data/realtime_asr_endpoints', {'source': 'speaker'}))
    target = next(row for row in endpoints['endpoints'] if 'Steam Streaming Speakers' in row['label'])
    settings['server'] = 'bundled'
    settings['speaker'].update(endpoint=target['endpoint'], follow_default=False, language='auto')
    event = app.call('/set/data/realtime_asr_settings', settings)
    app.record('realtime settings', event['status'] == 200, f"endpoints={len(endpoints['endpoints'])}")
    # The voice goes to this virtual device, so captions must refuse to read it.
    event = app.call('/set/enable/transcription_receive', timeout=150)
    reason = str(event.get('result'))
    app.record('captions refuse the device that carries the voice', event['status'] != 200 and 'realtime_endpoint_feedback' in reason,
               f"{event['status']} {reason[:170]}")
    voice = result(app.call('/get/data/voice_settings'))
    voice.update(output_device=CABLE)
    app.call('/set/data/voice_settings', voice)
    started = time.monotonic()
    event = app.call('/set/enable/transcription_receive', timeout=150)
    app.record('speaker toggle starts bundled ASR', event['status'] == 200 and event.get('result') is True,
               f"{time.monotonic()-started:.1f}s {event['status']} {str(event.get('result'))[:200]}")
    if event['status'] != 200:
        return
    pcm = load(OUT / os.environ.get('VOX_ASR_WAV', 'tts.wav'))
    thread = threading.Thread(target=lambda: play(SPEAKERS, bytes(9600) + pcm + bytes(96000)), daemon=True)
    sent = time.monotonic()
    thread.start()
    finals = []
    partials = 0
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        got = app.pump(.1)
        if got and got.get('endpoint') == '/run/realtime_caption':
            row = got.get('result') or {}
            if row.get('state') in ('final', 'finalized', 'done') or row.get('is_final'):
                finals.append(row)
            else:
                partials += 1
            print('  caption', str(row)[:190], flush=True)
        if finals and not thread.is_alive():
            break
    text = ' '.join(str(row.get('text', '')) for row in finals)
    app.record('speech server recognised the spoken TTS', '天気' in text or '散歩' in text,
               f'{time.monotonic()-sent:.1f}s partials={partials} text={text!r}')
    state = result(app.call('/get/data/realtime_asr_state'))
    app.record('realtime session healthy', state.get('speaker', {}).get('error_code') in (None, ''), str(state.get('speaker'))[:220])
    event = app.call('/set/disable/transcription_receive', timeout=20)
    app.record('speaker toggle stops realtime', event['status'] == 200, event['status'])


class Speaker:
    """A microphone never goes quiet the way an idle loopback does, so keep this one running."""
    def __init__(self):
        from collections import deque
        self.pending = deque()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        token = CancelToken()
        output = WindowsOutput(CABLE, 48000, 1, strict_underflow=False)
        silence = bytes(960)
        while not self.stop.is_set():
            output.write(self.pending.popleft() if self.pending else silence, token)
        output.close(drain=False, token=token)

    def say(self, pcm):
        self.pending.extend(pcm[i:i + 960] for i in range(0, len(pcm), 960))

    def wait(self):
        while self.pending:
            time.sleep(.05)


def direct_state(app):
    return result(app.call('/get/data/direct_voice_state'))


def wait_direct(app, check, timeout):
    deadline = time.monotonic() + timeout
    state = {}
    while time.monotonic() < deadline:
        state = direct_state(app)
        if check(state):
            return state
        time.sleep(.2)
    return state


def voice_direct(app):
    runtime = str(ROOT / 'build/rvc-runtime')
    model = str(M / 'rvc-saisho/model.pth')
    index = str(M / 'rvc-saisho/model.index')
    rate = float(os.environ.get('VOX_INDEX_RATE', '0'))
    settings = dict(mode='converted', runtime='', reference='', engine='rvc', rvc_runtime=runtime, rvc_model=model,
                    rvc_index=index if rate else '', rvc_pitch=0, rvc_index_rate=rate)
    event = app.call('/set/data/direct_voice_settings', settings)
    app.record('rvc settings', event['status'] == 200, event['status'])
    voice = result(app.call('/get/data/voice_settings'))
    voice.update(output_device=SPEAKERS, routing='external', mode='off')
    app.record('output device', app.call('/set/data/voice_settings', voice)['status'] == 200)
    state = direct_state(app)
    app.record('device route announced', state.get('output_route') == 'device', state.get('output_route'))
    sources = result(app.call('/get/data/direct_voice_sources'))
    app.record('sources listed', not sources.get('error') and len(sources['sources']) > 0, [s['label'] for s in sources['sources']])
    source = next(s['id'] for s in sources['sources'] if 'Steam Streaming Microphone' in s['label'])
    route = result(app.call('/get/data/voice_route'))
    app.record('route covers direct voice', route.get('covers_direct') is True, route.get('requested_muted'))
    pcm = load(OUT / 'tts.wav')
    speaker = Speaker()
    time.sleep(.3)
    # Seed-VC is Linux only and must say so.
    event = app.call('/run/start_direct_voice', {'source': source, 'mode': 'converted',
                                                 'options': {'runtime': runtime, 'reference': model}})
    app.record('seed-vc refused on windows', event['status'] == 409 and result(event).get('error_code') == 'vc_engine_linux_only',
               event['status'])
    started = time.monotonic()
    event = app.call('/run/start_direct_voice', {'source': source, 'mode': 'converted', 'options': dict(
        engine='rvc', runtime=runtime, model=model, index=index if rate else '', pitch=0, index_rate=rate)})
    app.record('rvc start accepted', event['status'] == 200, event['status'])
    state = wait_direct(app, lambda s: s.get('active') or s.get('error'), 195)
    app.record('rvc active', state.get('active') is True and not state.get('error'),
               f"{time.monotonic()-started:.1f}s {state.get('conversion_state')} {state.get('error')}")
    if not state.get('active'):
        speaker.stop.set()
        return
    with Recorder('Steam Streaming Speakers') as recorder:
        time.sleep(.5)
        begin = time.monotonic()
        said_ns = time.monotonic_ns()
        speaker.say(pcm + pcm + pcm)
        while speaker.pending:
            app.pump(.1)
            if time.monotonic() - begin > 40:
                break
        time.sleep(.5)
    converted = recorder.audio()
    state = direct_state(app)
    speech = speech_window(converted, 400)
    save(OUT / 'rvc-converted.wav', speech)
    voiced = float((np.abs(converted.astype(int)) > 400).mean())
    onset = next((f.captured_ns for f in recorder.frames if f.captured_ns > said_ns
                  and np.abs(np.frombuffer(f.audio.pcm, '<i2').astype(int)).max() > 600), None)
    source_onset = int(np.argmax(np.abs(np.frombuffer(pcm, '<i2').astype(int)) > 600)) / 48000
    delay = None if onset is None else (onset - said_ns) / 1e6 - source_onset * 1000 + 20
    print(f'  onset delay about {delay} ms (speech start in, to speech start out, 20 ms stamp bias removed)', flush=True)
    app.record('converted voice reached the device for the whole run',
               state.get('conversion_verified') is True and not state.get('error') and len(speech) / 48000 >= len(pcm) * 3 / 2 / 48000 * .9,
               f"in={len(pcm)*3/2/48000:.1f}s out={len(speech)/48000:.1f}s voiced={voiced:.2f} peak={np.abs(speech.astype(int)).max() if len(speech) else 0} "
               f"state={state.get('conversion_state')} error={state.get('error')}")
    if state.get('active'):
        app.call('/run/mute_voice')
        time.sleep(.5)
        with Recorder('Steam Streaming Speakers') as recorder:
            speaker.say(pcm[:192000])
            speaker.wait()
            time.sleep(.3)
        muted = recorder.audio()
        peak = int(np.abs(muted.astype(int)).max()) if len(muted) else 0
        # One step of 32767 is the audio engine's rounding, not voice.
        app.record('mute silences the device while conversion runs', peak <= 2 and direct_state(app).get('active') is True, f'peak={peak}')
        event = app.call('/run/resume_voice')
        time.sleep(.4)
        with Recorder('Steam Streaming Speakers') as recorder:
            speaker.say(pcm[:192000])
            speaker.wait()
            time.sleep(.4)
        resumed = recorder.audio()
        peak = int(np.abs(resumed.astype(int)).max()) if len(resumed) else 0
        app.record('resume brings the voice back', peak > 1000, f'peak={peak}')
    stopped = time.monotonic()
    app.call('/run/stop_direct_voice')
    state = wait_direct(app, lambda s: not s.get('requested') and not s.get('pending') and not s.get('stopping'), 10)
    app.record('rvc stops', not state.get('requested') and not state.get('stopping'), f'{time.monotonic()-stopped:.2f}s')
    # With conversion off, the original voice still reaches VRChat through the same device.
    event = app.call('/set/data/direct_voice_settings', dict(settings, mode='passthrough', engine='seed-vc'))
    event = app.call('/run/start_direct_voice', {'source': source})
    app.record('forwarding accepted', event['status'] == 200, str(result(event))[:120])
    state = wait_direct(app, lambda s: s.get('active') or s.get('error'), 8)
    app.record('forwarding active', state.get('active') is True, state.get('error'))
    with Recorder('Steam Streaming Speakers') as recorder:
        speaker.say(pcm[:192000])
        speaker.wait()
        time.sleep(.4)
    forwarded = speech_window(recorder.audio(), 400)
    source_clip = np.frombuffer(pcm[:192000], '<i2').astype(float)
    length = min(len(forwarded), len(source_clip))
    similar = 0.0
    if length > 4800:
        a = forwarded[:length].astype(float)
        b = source_clip[:length]
        spectrum = np.fft.irfft(np.fft.rfft(a, 2 * length) * np.conj(np.fft.rfft(b, 2 * length)))
        similar = float(np.abs(spectrum).max() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
    app.record('original voice forwarded unchanged', similar > .8, f'correlation={similar:.3f} seconds={len(forwarded)/48000:.2f}')
    app.call('/run/stop_direct_voice')
    wait_direct(app, lambda s: not s.get('requested') and not s.get('stopping'), 6)
    speaker.stop.set()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if 'rvc' in sys.argv[1:]:
        os.environ['VOX_MIC_AS_LOOPBACK'] = CABLE
        os.environ['VOX_ROUTER_SITE'] = str(SCRATCH / 'site_router')
    app = harness.Backend(OUT)
    try:
        app.start()
        if 'rvc' in sys.argv[1:]:
            voice_direct(app)
        if 'tts' in sys.argv[1:] or len(sys.argv) == 1:
            tts(app)
        if 'asr' in sys.argv[1:] or len(sys.argv) == 1:
            asr(app)
    finally:
        app.close()


if __name__ == '__main__':
    main()
