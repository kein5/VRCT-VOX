"""Windows soak with everything on: RVC, TTS, GPU recognition, translation, the real SteamVR.

The "person" is a silent virtual output (CABLE). Its loopback stands in for the microphone of RVC
and is what the captions hear; the voice (RVC and TTS) comes out on another (SPEAKERS), so nothing
feeds back. The real microphone is never opened (see site/sitecustomize.py and site_router).
Usage: win_soak_full.py [seconds] [out-name] [realtime|whisper]
"""
import collections
import copy
import csv
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.request
import wave

SCRATCH = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('VOX_FIELD_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(SCRATCH))
sys.path.insert(0, str(ROOT / 'src-python'))
import numpy as np  # noqa: E402
import psutil  # noqa: E402
import harness  # noqa: E402
import steamvr_null  # noqa: E402

from models.audio_routing.devices_windows import WindowsOutput, enumerate_endpoints  # noqa: E402
from models.transcription.capture_windows import WindowsCapture  # noqa: E402
from models.tts.speechcpp_tts import CancelToken  # noqa: E402

SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
OUT = ROOT / 'build/model-test' / (sys.argv[2] if len(sys.argv) > 2 else 'win-soak-full')
ASR = sys.argv[3] if len(sys.argv) > 3 else 'realtime'
if len(sys.argv) > 4:
    os.environ['VOX_SPEECH_DEVICE'] = sys.argv[4]
WARMUP = min(300, SECONDS / 3)
SPEAK_EVERY, SAMPLE_EVERY, CHAT_EVERY = 15.0, 30.0, 60.0
SPEAKERS = '["Windows WASAPI", "Speakers (Steam Streaming Speakers)"]'
CABLE = '["Windows WASAPI", "Speakers (Steam Streaming Microphone)"]'
M = ROOT / 'build/model-test/win-voice'
RUNTIME, MODEL = str(ROOT / 'build/rvc-runtime'), str(M / 'rvc-saisho/model.pth')
TTS_MODEL = str(M / 'irodori-v41-q8/Irodori-TTS-866M-MF-v4.1-Q8_0.gguf')
ASR_MODEL = str(M / 'qwen3-asr-06b-q8/Qwen3-ASR-0.6B-Q8_0.gguf')
VAD_MODEL = str(M / 'silero-vad-v62/silero-vad-309K-v6.2-F32.gguf')
HEARD = '/run/transcription_receive_speaker_message'
CAPTION = '/run/realtime_caption'
POLLED = ('/get/data/direct_voice_state', '/get/data/voice_status', '/get/data/speech_server_state', '/get/data/realtime_asr_state')
CHATS = ('こんにちは、調子はどうですか。', '今日はとても良い天気ですね。', 'また明日会いましょう。')

STEAM_VR = ROOT / 'build/model-test/steamvr'
os.environ.update(VR_CONFIG_PATH=str(STEAM_VR / 'config'), VR_LOG_PATH=str(STEAM_VR / 'logs'),
                  VOX_MIC_AS_LOOPBACK=CABLE, VOX_ROUTER_SITE=str(SCRATCH / 'site_router'))


def result(event):
    return (event or {}).get('result') or {}


def load16(name):
    with wave.open(str(ROOT / 'build/model-test/windows-field/wavs' / f'{name}.wav'), 'rb') as reader:
        samples = np.frombuffer(reader.readframes(reader.getnframes()), '<i2').astype(float)
    return np.interp(np.arange(len(samples) * 3) / 3, np.arange(len(samples)), samples).astype('<i2').tobytes()


def load48(path):
    with wave.open(str(path), 'rb') as reader:
        return reader.readframes(reader.getnframes())


class RealVr(harness.Backend):
    """The real OpenVR binding, but the test's startup hook stays for the loopback microphone."""

    def __init__(self, out):
        real_popen = subprocess.Popen

        def popen(args, **kwargs):
            kwargs['env'] = {k: v for k, v in kwargs['env'].items()
                             if k not in ('VOX_FAKE_VR_OUT', 'VOX_FAKE_OCR_FRAME', 'VOX_FAKE_DETECTOR_CONFIDENCE')}
            return real_popen(args, **kwargs)

        harness.subprocess.Popen = popen
        try:
            super().__init__(out)
        finally:
            harness.subprocess.Popen = real_popen


class Speaker:
    def __init__(self):
        self.pending = collections.deque()
        self.stop = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        token = CancelToken()
        try:
            output = WindowsOutput(CABLE, 48000, 1, strict_underflow=False)
            silence = bytes(960)
            while not self.stop.is_set():
                output.write(self.pending.popleft() if self.pending else silence, token)
            output.close(drain=False, token=token)
        except Exception as error:  # noqa: BLE001
            self.error = repr(error)

    def say(self, pcm):
        self.pending.extend(pcm[i:i + 960] for i in range(0, len(pcm), 960))


class Monitor:
    """Counts the frames that carry a voice on the output, without keeping any audio."""

    def __init__(self, label):
        endpoint = next(r['endpoint'] for r in enumerate_endpoints('speaker') if label in r['label'])
        self.frames = self.loud = 0
        self.errors = []
        self.capture = WindowsCapture(endpoint, 'speaker', self._add, self.errors.append)

    def _add(self, frame):
        pcm = np.frombuffer(frame.audio.pcm, '<i2')
        self.frames += 1
        if pcm.size and int(np.abs(pcm.astype(int)).max()) > 600:
            self.loud += 1
        return True

    def take(self):
        values = self.frames, self.loud
        self.frames = self.loud = 0
        return values


class Sampler:
    def __init__(self, pid):
        self.root = psutil.Process(pid)
        self.last = None

    @staticmethod
    def _gpu():
        try:
            text = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu', '--format=csv,noheader,nounits'],
                                  capture_output=True, text=True, timeout=10).stdout.strip()
            used, busy = text.split(',')
            return int(used), int(busy)
        except Exception:  # noqa: BLE001
            return None, None

    @staticmethod
    def _named(name):
        memory, count = 0, 0
        for process in psutil.process_iter(['name']):
            try:
                if (process.info['name'] or '').lower() == name:
                    memory += process.memory_info().private
                    count += 1
            except psutil.Error:
                pass
        return count, round(memory / 2 ** 20, 1)

    def adapters(self):
        """Per process and adapter: dedicated and shared GPU memory in MB, from the Windows counters."""
        command = ("(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage','\\GPU Process Memory(*)\\Shared Usage').CounterSamples"
                   " | Where-Object CookedValue -gt 1000000 | ForEach-Object { $_.Path + '|' + $_.CookedValue }")
        try:
            text = subprocess.run(['pwsh', '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=25).stdout
        except Exception:  # noqa: BLE001
            return {}
        names = {}
        for process in [self.root] + self.root.children(recursive=True):
            try:
                names[process.pid] = process.name()
            except psutil.Error:
                pass
        table = {}
        for line in text.splitlines():
            found = re.search(r'pid_(\d+)_luid_(\S+?)_phys_\d+\)\\(dedicated|shared)[^|]*\|([\d.]+)', line)
            if found and int(found[1]) in names:
                key = f"{names[int(found[1])]}:{found[1]} {found[2][-6:]}"
                table.setdefault(key, {})[found[3]] = round(float(found[4]) / 2 ** 20)
        return table

    def row(self, elapsed):
        processes = [self.root] + self.root.children(recursive=True)
        private = handles = threads = 0
        cpu = 0.0
        for process in processes:
            try:
                with process.oneshot():
                    private += process.memory_info().private
                    handles += process.num_handles()
                    threads += process.num_threads()
                    times = process.cpu_times()
                    cpu += times.user + times.system
            except psutil.Error:
                pass
        busy = None if self.last is None else (cpu - self.last[1]) / max(elapsed - self.last[0], .001) * 100
        self.last = (elapsed, cpu)
        vram, gpu = self._gpu()
        vrchat, vrchat_mb = self._named('vrchat.exe')
        return dict(seconds=round(elapsed, 1), processes=len(processes), private_mb=round(private / 2 ** 20, 1), handles=handles,
                    threads=threads, cpu_percent=None if busy is None else round(busy, 1), vram_mb=vram, gpu_percent=gpu,
                    free_ram_mb=round(psutil.virtual_memory().available / 2 ** 20), vrchat=vrchat, vrchat_mb=vrchat_mb)


def slope(rows, key):
    late = [r for r in rows if r['seconds'] >= WARMUP and r.get(key) is not None]
    if len(late) < 3:
        return None
    return round(float(np.polyfit(np.array([r['seconds'] / 60 for r in late]), np.array([r[key] for r in late], float), 1)[0]), 3)


def overlays(tag):
    done = subprocess.run([str(ROOT / '.venv/Scripts/python.exe'), str(SCRATCH / 'steamvr_overlays.py'), str(OUT / tag)],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    for line in done.stdout.splitlines():
        if line.startswith('OVERLAYS '):
            return json.loads(line[9:])
    return {'failed': (done.stdout + done.stderr)[-300:]}


def wait_direct(app, check, timeout):
    deadline = time.monotonic() + timeout
    state = {}
    while time.monotonic() < deadline:
        state = result(app.call('/get/data/direct_voice_state'))
        if check(state):
            return state
        time.sleep(.3)
    return state


def setup(app, init):
    your, target = copy.deepcopy(init['/get/data/selected_your_languages']), copy.deepcopy(init['/get/data/selected_target_languages'])
    tab = init['/get/data/selected_tab_no']
    your[tab]['1'].update(language='Japanese', country='Japan', enable=True)
    target[tab]['1'].update(language='English', country='United States', enable=True)
    for extra in ('2', '3'):
        if extra in target[tab]:
            target[tab][extra]['enable'] = False
    app.call('/set/data/selected_your_languages', your)
    app.call('/set/data/selected_target_languages', target)
    profiles = dict(japanese=dict(model=TTS_MODEL, vad_model='', voice_file='', device='auto', low_latency=False),
                    multilingual=dict(model='', vad_model='', voice_file='', device='auto', low_latency=False),
                    asr=dict(model=ASR_MODEL, vad_model=VAD_MODEL, voice_file='', device='auto', low_latency=False))
    app.record('speech server settings', app.call('/set/data/speech_server_settings', dict(version=1, profiles=profiles))['status'] == 200)
    voice = result(app.call('/get/data/voice_settings'))
    voice.update(mode='original', japanese_server='bundled', output_device=SPEAKERS, routing='external')
    app.record('voice settings', app.call('/set/data/voice_settings', voice)['status'] == 200)
    event = app.call('/set/enable/translation', timeout=120)
    app.record('translation on', event['status'] == 200 and event.get('result') is True, str(event.get('result'))[:100])
    event = app.call('/set/enable/overlay_large_log', timeout=30)
    app.record('subtitle overlay on (real SteamVR)', event['status'] == 200, event['status'])


def start_tts(app):
    status = result(app.call('/get/data/voice_status'))
    started = time.monotonic()
    event = app.call('/run/enable_tts', {'generation': status['tts_generation']}, timeout=180)
    app.record('tts on', event['status'] == 200 and result(event).get('tts_enabled') is True,
               f"{time.monotonic() - started:.1f}s {str(result(event))[:160]}")


def start_rvc(app):
    settings = dict(mode='converted', runtime='', reference='', engine='rvc', rvc_runtime=RUNTIME, rvc_model=MODEL,
                    rvc_index='', rvc_pitch=0, rvc_index_rate=0.0)
    app.record('rvc settings', app.call('/set/data/direct_voice_settings', settings)['status'] == 200)
    sources = result(app.call('/get/data/direct_voice_sources'))
    source = next(s['id'] for s in sources['sources'] if 'Steam Streaming Microphone' in s['label'])
    started = time.monotonic()
    event = app.call('/run/start_direct_voice', {'source': source, 'mode': 'converted', 'options': dict(
        engine='rvc', runtime=RUNTIME, model=MODEL, index='', pitch=0, index_rate=0.0)})
    app.record('rvc start accepted', event['status'] == 200, f"{event['status']} {str(result(event))[:160]}")
    state = wait_direct(app, lambda s: s.get('active') or s.get('error'), 195)
    app.record('rvc active', state.get('active') is True and not state.get('error'),
               f"{time.monotonic() - started:.1f}s {state.get('conversion_state')} {state.get('error')}")
    return state.get('active') is True


def start_asr(app):
    if ASR == 'realtime':
        settings = result(app.call('/get/data/realtime_asr_settings'))
        endpoints = result(app.call('/get/data/realtime_asr_endpoints', {'source': 'speaker'}))
        target = next(row for row in endpoints['endpoints'] if 'Steam Streaming Microphone' in row['label'])
        settings['server'] = 'bundled'
        settings['speaker'].update(endpoint=target['endpoint'], follow_default=False, language='auto')
        app.record('realtime settings', app.call('/set/data/realtime_asr_settings', settings)['status'] == 200)
    else:
        app.call('/set/data/selected_transcription_engine', 'Whisper')
        app.call('/set/data/selected_whisper_weight_type', 'tiny')
        devices = result(app.call('/get/data/selectable_transcription_compute_device_list'))
        cuda = next(d for d in devices if d.get('device') == 'cuda')
        event = app.call('/set/data/selected_transcription_compute_device', cuda)
        app.record('whisper on the gpu', event['status'] == 200, cuda.get('device_name'))
        app.call('/set/disable/auto_speaker_select')
        names = result(app.call('/get/data/selectable_speaker_device_list'))
        rendered = names if isinstance(names, list) else list(names.values())
        name = next(str(n.get('name') if isinstance(n, dict) else n) for n in rendered if 'Steam Streaming Microphone' in str(n))
        app.record('virtual speaker selected', app.call('/set/data/selected_speaker_device', name)['status'] == 200, name)
    started = time.monotonic()
    event = app.call('/set/enable/transcription_receive', timeout=180)
    app.record('recognition on', event['status'] == 200 and event.get('result') is True,
               f"{time.monotonic() - started:.1f}s {event['status']} {str(event.get('result'))[:200]}")
    return event['status'] == 200


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    guard = OUT / 'mic-guard.log'
    guard.write_text('', encoding='utf-8')
    os.environ['VOX_BLOCK_MIC'] = str(guard)
    english = [load16('en-1'), load16('en-2')]
    voices = english if ASR == 'whisper' else [load48(ROOT / 'build/model-test/win-e2e/tts.wav')] + english
    print('steamvr', steamvr_null.processes(), flush=True)
    steamvr_null.start()
    speaker = monitor = None
    rows, heard, failures, latencies, windows = [], [], [], [], []
    endpoints = collections.Counter()
    latest = {}
    spoken = chats = chat_ok = 0
    slots = set()
    said_at = []
    began = None
    app = RealVr(OUT)
    overlay_state = {}
    chosen = {}

    def note(now, endpoint, status, detail):
        if len(failures) < 60:
            failures.append(dict(seconds=None if began is None else round(now - began, 1), endpoint=endpoint, status=status, detail=str(detail)[:300]))
        print(f'  FAILURE {endpoint} {status} {str(detail)[:200]}', flush=True)

    def handle(event, now):
        nonlocal chat_ok
        endpoint, status = event.get('endpoint'), event.get('status')
        endpoints[f'{endpoint} {status}'] += 1
        answer = event.get('result')
        final = False
        if endpoint == CAPTION:
            row = answer or {}
            final = row.get('state') in ('final', 'finalized', 'done') or bool(row.get('is_final'))
            text = row.get('text')
        elif endpoint == HEARD:
            final = True
            text = ((answer or {}).get('original') or {}).get('message')
        if final and began is not None:
            heard.append(dict(seconds=round(now - began, 1), text=text))
            slot = int((now - began - 3) // SPEAK_EVERY)
            if slot not in slots and 0 <= slot < len(said_at):
                slots.add(slot)
                latencies.append(now - said_at[slot])
        if endpoint == '/get/data/direct_voice_state' and (answer or {}).get('error') and began is not None and not (OUT / 'rvc-stop.txt').exists():
            (OUT / 'rvc-stop.txt').write_text(f"{time.strftime('%H:%M:%S')} {now - began:.1f}s {answer.get('error')}\n", encoding='utf-8')
        if endpoint in POLLED:
            latest[endpoint] = answer
        elif endpoint == '/run/send_message_box' and status == 200:
            chat_ok += 1
        elif (status or 200) >= 400 or 'error' in str(endpoint):
            note(now, endpoint, status, answer)

    try:
        init = app.start()
        setup(app, init)
        speaker = Speaker()
        time.sleep(.5)
        start_tts(app)
        rvc = start_rvc(app)
        recognition = start_asr(app)
        if not (rvc and recognition):
            return
        monitor = Monitor('Steam Streaming Speakers')
        monitor.capture.start()
        sampler = Sampler(app.process.pid)
        adapters_start = sampler.adapters()
        print('gpu memory by process', json.dumps(adapters_start, ensure_ascii=False), flush=True)
        servers = result(app.call('/get/data/speech_server_state'))
        for profile, row in servers.items():
            if row.get('base_url'):
                with urllib.request.urlopen(row['base_url'] + '/v1/models', timeout=5) as response:
                    chosen[profile] = [m['speech'].get('device') for m in json.loads(response.read())['data']]
        app.record('speech.cpp devices', bool(chosen), chosen)
        began = time.monotonic()
        next_speak, next_sample, next_chat = began + 3, began, began + 20
        next_direct = began + 3.0
        with (OUT / 'samples.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = None
            while (now := time.monotonic()) - began < SECONDS:
                if now >= next_sample:
                    row = sampler.row(now - began)
                    row['output_frames'], row['output_loud'] = monitor.take()
                    rows.append(row)
                    if writer is None:
                        writer = csv.DictWriter(stream, list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    stream.flush()
                    print(f"{row['seconds']:7.0f}s private={row['private_mb']} handles={row['handles']} threads={row['threads']} cpu={row['cpu_percent']} "
                          f"vram={row['vram_mb']} gpu={row['gpu_percent']} loud={row['output_loud']}/{row['output_frames']} vrchat={row['vrchat_mb']} "
                          f"spoken={spoken} heard={len(slots)} finals={len(heard)} chat={chat_ok}/{chats} fail={len(failures)}", flush=True)
                    for endpoint in POLLED:
                        app.send(endpoint)
                    direct = latest.get('/get/data/direct_voice_state') or {}
                    if latest and (direct.get('error') or direct.get('active') is False):
                        note(now, 'direct_voice_state', 0, {k: direct.get(k) for k in ('active', 'error', 'conversion_state')})
                    next_sample += SAMPLE_EVERY
                if now >= next_direct:
                    app.send('/get/data/direct_voice_state')
                    next_direct += 3.0
                if now >= next_speak:
                    speaker.say(voices[spoken % len(voices)])
                    said_at.append(now)
                    spoken += 1
                    next_speak += SPEAK_EVERY
                if now >= next_chat:
                    chats += 1
                    app.send('/run/send_message_box', {'id': f'soak-{chats}', 'message': CHATS[chats % len(CHATS)]})
                    next_chat += CHAT_EVERY
                event = app.pump(.05)
                if event and event.get('status') != 348:
                    handle(event, time.monotonic())
        adapters_end = sampler.adapters()
        print('gpu memory by process at the end', json.dumps(adapters_end, ensure_ascii=False), flush=True)
        (OUT / 'gpu-memory.json').write_text(json.dumps(dict(start=adapters_start, end=adapters_end), ensure_ascii=False, indent=1), encoding='utf-8')
        overlay_state = overlays('end')
        state = wait_direct(app, lambda s: True, 2)
        app.record('rvc still healthy at the end', state.get('active') is True and not state.get('error'), {k: state.get(k) for k in ('active', 'error', 'conversion_state', 'conversion_verified')})
        app.call('/run/stop_direct_voice')
        wait_direct(app, lambda s: not s.get('requested') and not s.get('stopping'), 15)
        app.call('/run/disable_tts', timeout=30)
        app.record('recognition off', app.call('/set/disable/transcription_receive', timeout=60)['status'] == 200)
        app.call('/set/disable/overlay_large_log', timeout=30)
    finally:
        if monitor is not None:
            monitor.capture.stop()
        if speaker is not None:
            speaker.stop.set()
            speaker.thread.join(5)
        app.close()
        steamvr_null.stop()
    stderr = (OUT / 'stderr.log').read_text(encoding='utf-8', errors='replace')
    summary = dict(
        asr=ASR, speech_devices=chosen, vrchat_samples=sum(1 for r in rows if r['vrchat']), seconds=SECONDS, warmup_seconds=WARMUP, spoken=spoken, utterances_heard=len(slots), finals=len(heard), chats_sent=chats, chats_ok=chat_ok,
        failure_count=len(failures), failures=failures[:20],
        latency_seconds=dict(median=round(float(np.median(latencies)), 2), p95=round(float(np.percentile(latencies, 95)), 2)) if latencies else None,
        first=rows[0] if rows else None, after_warmup=next((r for r in rows if r['seconds'] >= WARMUP), None), last=rows[-1] if rows else None,
        slope_per_minute={k: slope(rows, k) for k in ('private_mb', 'handles', 'threads', 'vram_mb')},
        cpu_range=[min(r['cpu_percent'] for r in rows[1:]), max(r['cpu_percent'] for r in rows[1:])] if len(rows) > 1 else None,
        gpu_range=[min(r['gpu_percent'] for r in rows), max(r['gpu_percent'] for r in rows)] if rows and rows[0]['gpu_percent'] is not None else None,
        vram_peak=max((r['vram_mb'] or 0) for r in rows) if rows else None,
        output_loud_min=min((r['output_loud'] for r in rows[1:]), default=None),
        speaker_error=speaker.error if speaker else None, monitor_errors=monitor.errors[:5] if monitor else None,
        mic_refused=guard.read_text(encoding='utf-8').count('REFUSED'), stderr_tracebacks=stderr.count('Traceback'),
        overlays=overlay_state, heard_sample=heard[:8], endpoints=dict(endpoints.most_common(40)),
        last_state={k: str(v)[:400] for k, v in latest.items()},
    )
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)


if __name__ == '__main__':
    main()
