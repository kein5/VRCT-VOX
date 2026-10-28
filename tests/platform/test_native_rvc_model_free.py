"""Private PipeWire acceptance for the fixed RVC process, with fake inference.

No physical input, target model, network service, or VRChat is involved.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import time

import pytest

from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
from models.audio_routing.source_bridge import select_source
from tools.voice_acceptance import graph_snapshot, loopback, private_graph, wait_for
from tools.voice_b_poc import ToneCapture, settled, tone

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != 'linux' or os.environ.get('VRCT_TEST_RVC_ROUTE') != '1',
                               reason='opt-in private PipeWire RVC contract test')


@pytest.mark.parametrize('end', ['stop', 'worker_death'])
def test_rvc_contract_worker_to_private_mic_and_silence(tmp_path, end):
    from models.voice_conversion.rvc_process import RVCProcess
    from test_native_realtime import SyntheticProducer
    runtime = tmp_path / 'runtime'
    for name in ('venv/bin', 'engine', 'assets'):
        (runtime / name).mkdir(parents=True)
    model = tmp_path / 'fake.pth'
    model.touch()  # Deliberately not an inference model; only the fake interpreter reads it.
    interpreter = runtime / 'venv/bin/python'
    interpreter.write_text('#!' + sys.executable + '\n' + '''
import sys,time,struct
sys.path.insert(0, 'src-python')
from models.voice_conversion import protocol as p
assert sys.argv[1:4] == ['-u', '-m', 'integrations.rvc.live_worker']
session = sys.argv[sys.argv.index('--session')+1]
out = sys.stdout.buffer
out.write(p.encode_packet(p.ready_info(session, engine='rvc'))); out.flush()
while True:
    info, pcm = p.read_packet(sys.stdin.buffer, timeout=3)
    samples = struct.unpack('<3840h', pcm)
    output = struct.pack('<3840h', *(int(x/2) for x in samples))
    out.write(p.encode_packet(dict(info, type='output', state='converted'), output)); out.flush()
''')
    interpreter.chmod(0o700)
    report = dict(real_rvc=False, physical_capture=False, vrchat=False, case=end, status='failed')
    try:
        with private_graph(config_fragment=ROOT/'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
            loopback(stack, 'vrct.native.caption')
            producer = stack.enter_context(SyntheticProducer(tone(440)*80))
            input_observer = ToneCapture(stack, 'vrct.native.caption.source')
            settled(input_observer, time.monotonic_ns(), 'input_not_stable', silent=True)
            capture = ToneCapture(stack, SOURCE)
            gate = PipeWireGate()
            gate.set_muted(False, gate.inspect()['identity'])
            vc = RVCProcess(dict(engine='rvc', runtime=str(runtime), model=str(model),
                                 index='', pitch=0, index_rate=0.0))
            stack.callback(vc.close)
            vc.start(source=select_source(graph_snapshot(), 'vrct.native.caption.source'))
            wait_for(lambda: vc.health()['active'] or vc.health()['error'], timeout=5)
            assert vc.health()['active'], vc.health()
            settled(capture, time.monotonic_ns(), 'ready_not_silent', silent=True)
            producer.play()
            wait_for(lambda: capture.snapshot()['nonzero_frames'] > 5 or vc.health()['error'], timeout=5)
            assert vc.health()['conversion_verified'] and not vc.health()['error'], vc.health()
            assert capture.snapshot()['nonzero_frames'] > 5
            if end == 'stop':
                vc.stop()
            else:
                vc._child.kill()
                wait_for(lambda: vc.health()['error'], timeout=3)
            assert vc.close(timeout=3)
            settled(capture, time.monotonic_ns(), 'raw_fallback_after_stop', silent=True)
            # Input is still present throughout the two-second output-silence hold.
            assert input_observer.snapshot()['nonzero_frames'] > 50
            report.update(status='passed', after=vc.health(), silence_hold_ms=2000,
                          capture=capture.snapshot())
    finally:
        (tmp_path/'report.json').write_text(json.dumps(report, indent=2)+'\n')
