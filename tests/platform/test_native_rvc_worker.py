"""Opt-in real RVC with consented local weights and synthetic private audio."""
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
import sys
import time
import wave

import pytest

from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
from models.audio_routing.source_bridge import select_source
from tools.voice_acceptance import graph_snapshot, loopback, private_graph, wait_for
from tools.voice_b_poc import ToneCapture, settled

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != 'linux' or os.environ.get('VRCT_TEST_LIVE_RVC') != '1',
                               reason='consented RVC runtime, model/index and synthetic input required')


@pytest.mark.parametrize('index_rate', [0.0, 0.5])
@pytest.mark.parametrize('end', ['stop', 'worker_death'])
def test_real_rvc_to_private_microphone_and_shutdown(tmp_path, monkeypatch, index_rate, end):
    from models.voice_conversion import process
    from models.voice_conversion.rvc_process import RVCProcess
    from test_native_realtime import SyntheticProducer
    runtime = Path(os.environ['VRCT_RVC_RUNTIME']).resolve()
    with wave.open(os.environ['VRCT_RVC_INPUT']) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
        pcm = wav.readframes(wav.getnframes())
    run_seconds = float(os.environ.get('VRCT_RVC_RUN_SECONDS', '0'))
    assert 0 <= run_seconds <= 1800 and pcm
    if run_seconds:
        pcm *= math.ceil((run_seconds+5)*48000*2/len(pcm))
    report = dict(status='failed', real_rvc=True, physical_capture=False, vrchat=False,
                  perceptual_quality=False, index_rate=index_rate, case=end, writes=[],
                  boundary='capture block end to accepted OS write; excludes ADC and VRChat',
                  stop_samples_are_percentiles=False, sustained_seconds=run_seconds)
    output = process._output
    class Measured:
        def __init__(self, endpoint):
            self.inner = output(endpoint)
        def write(self, pcm, token):
            self.inner.write(pcm, token)
            report['writes'].append(dict(input_end_to_write_ms=(time.monotonic_ns()-token.end_ns)/1e6,
                                         nonzero=any(pcm)))
        def close(self, **kwargs):
            return self.inner.close(**kwargs)
    monkeypatch.setattr(process, '_output', Measured)
    vc = None
    try:
        with private_graph(config_fragment=ROOT/'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
            loopback(stack, 'vrct.native.caption')
            producer = stack.enter_context(SyntheticProducer(pcm))
            input_observer = ToneCapture(stack, 'vrct.native.caption.source')
            settled(input_observer, time.monotonic_ns(), 'input_not_stable', silent=True)
            capture = ToneCapture(stack, SOURCE)
            gate = PipeWireGate()
            gate.set_muted(False, gate.inspect()['identity'])
            settled(capture, time.monotonic_ns(), 'initial_output_not_silent', silent=True)
            vc = RVCProcess(dict(engine='rvc', runtime=str(runtime),
                model=str(Path(os.environ['VRCT_RVC_MODEL']).resolve()),
                index=str(Path(os.environ['VRCT_RVC_INDEX']).resolve()), pitch=0, index_rate=index_rate))
            stack.callback(vc.close)
            begin = time.monotonic_ns()
            vc.start(source=select_source(graph_snapshot(), 'vrct.native.caption.source'))
            wait_for(lambda: vc.health()['active'] or vc.health()['error'], timeout=65)
            assert vc.health()['active'], vc.health()
            report['start_to_active_ms'] = (time.monotonic_ns()-begin)/1e6
            baseline = capture.snapshot()['nonzero_frames']
            producer.play()
            wait_for(lambda: capture.snapshot()['nonzero_frames'] > baseline+10 or vc.health()['error'], timeout=10)
            assert vc.health()['conversion_verified'] and not vc.health()['error'], vc.health()
            assert capture.snapshot()['nonzero_frames'] > baseline+10
            until = time.monotonic() + run_seconds
            while time.monotonic() < until:
                assert vc.health()['active'] and not vc.health()['error'], vc.health()
                time.sleep(.02)
            before = time.monotonic_ns()
            if end == 'stop':
                vc.stop()
            else:
                vc._child.kill()
                wait_for(lambda: vc.health()['error'], timeout=3)
            assert vc.close(timeout=3)
            silent = settled(capture, before, 'rvc_stopped_not_silent', silent=True)
            # The synthetic source continues after Stop/kill; it cannot become a raw fallback.
            assert input_observer.snapshot()['nonzero_frames'] > 50
            assert vc._child.poll() is not None
            report.update(status='passed', after=vc.health(), capture=capture.snapshot(),
                          silence_hold_ms=2000, stop_to_silent_read_ms=(silent-before)/1e6)
    finally:
        if vc:
            report['last_health'] = vc.health()
        (tmp_path/'report.json').write_text(json.dumps(report, indent=2)+'\n')
