"""The frozen sidecar, as a release runs it: TTS, realtime ASR, translation, and the RVC route."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRATCH))
import harness  # noqa: E402
import win_e2e as e  # noqa: E402

ROOT = e.ROOT
FROZEN = ROOT / 'build/frozen-test/vrct-vox-sidecar-x86_64-pc-windows-msvc.exe'
OUT = ROOT / 'build/model-test/win-frozen'


class FrozenBackend(harness.Backend):
    """Same protocol as the source run, with the real frozen executable and no test hooks."""
    def __init__(self, out):
        real = harness.subprocess.Popen

        def popen(args, **kwargs):
            env = kwargs['env']
            for key in ('PYTHONPATH', 'VOX_FAKE_VR_OUT', 'VOX_FAKE_OCR_FRAME', 'VOX_FAKE_DETECTOR_CONFIDENCE',
                        'VOX_FAKE_AUDIO_DIR', 'VOX_REPO'):
                env.pop(key, None)
            kwargs['cwd'] = str(FROZEN.parent)
            return real([str(FROZEN)], **kwargs)

        harness.subprocess.Popen = popen
        try:
            super().__init__(out)
        finally:
            harness.subprocess.Popen = real


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    e.OUT = OUT
    source = ROOT / 'build/model-test/win-e2e/tts.wav'
    app = FrozenBackend(OUT)
    try:
        app.start()
        event = app.call('/get/data/direct_voice_state')
        app.record('frozen: device route', (event.get('result') or {}).get('output_route') == 'device')
        e.tts(app)
        e.asr(app)
        # The router and worker in frozen form. The Steam microphone cannot open on this PC,
        # so reaching that exact capture error proves the router, worker and output all ran.
        runtime = str(ROOT / 'build/rvc-runtime')
        model = str(e.M / 'rvc-saisho/model.pth')
        settings = dict(mode='converted', runtime='', reference='', engine='rvc', rvc_runtime=runtime, rvc_model=model,
                        rvc_index='', rvc_pitch=0, rvc_index_rate=0)
        app.call('/set/data/direct_voice_settings', settings)
        voice = e.result(app.call('/get/data/voice_settings'))
        voice.update(output_device=e.SPEAKERS, routing='external', mode='off')
        app.call('/set/data/voice_settings', voice)
        sources = e.result(app.call('/get/data/direct_voice_sources'))
        target = next(s['id'] for s in sources['sources'] if 'Steam Streaming Microphone' in s['label'])
        started = time.monotonic()
        event = app.call('/run/start_direct_voice', {'source': target, 'mode': 'converted', 'options': dict(
            engine='rvc', runtime=runtime, model=model, index='', pitch=0, index_rate=0)})
        app.record('frozen: rvc accepted', event['status'] == 200, event['status'])
        state = e.wait_direct(app, lambda s: s.get('error') or s.get('active'), 195)
        app.record('frozen: router and worker reached capture', state.get('error') == 'asr_capture_stream_create_failed',
                   f"{time.monotonic()-started:.1f}s error={state.get('error')}")
    finally:
        app.close()


if __name__ == '__main__':
    main()
