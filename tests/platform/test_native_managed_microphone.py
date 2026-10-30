"""Real generated pw-loopback commands; isolated audio, no physical microphone."""
import os
import shutil
import sys
import time

import pytest

from models.audio_routing.managed_microphone import loopback_commands
from models.audio_routing.managed_route import VoiceRoute
from models.audio_routing.mute_state import MuteState
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE, VC_SINK
from models.tts.tts_scheduler import VoiceEventBus
from tools.voice_acceptance import private_graph, start_process, wait_for
from tools.voice_b_poc import Producer, ToneCapture, settled

pytestmark = pytest.mark.skipif(sys.platform != 'linux' or os.getenv('VRCT_TEST_AUTO_MIC') != '1',
                               reason='opt-in private PipeWire endpoints')


def test_generated_services_start_muted_and_survive_control_shutdown(tmp_path):
    with private_graph() as stack:
        processes = [start_process(stack, args) for args in loopback_commands(shutil.which('pw-loopback')).values()]
        gate = PipeWireGate()
        def complete():
            try:
                return gate.inspect_pair()
            except RuntimeError:
                return None
        initial = wait_for(complete, code='managed_endpoints_missing')
        assert initial['source']['muted'] is True
        capture = ToneCapture(stack, SOURCE)
        producer = Producer(stack, VC_SINK, 440)
        settled(capture, time.monotonic_ns(), 'new_endpoint_not_muted', silent=True)
        bus = VoiceEventBus()
        control = VoiceRoute(bus, gate=gate, store=MuteState(tmp_path/'mute.json'))
        stack.callback(bus.close)
        stack.callback(control.close)
        control.configure(True)
        wait_for(lambda: control.status()['ready'] and not control.status()['pending'])
        control.resume()
        settled(capture, time.monotonic_ns(), 'resume_did_not_pass_audio', present=(440,))
        assert control.close()
        settled(capture, time.monotonic_ns(), 'shutdown_did_not_mute', silent=True)
        assert gate.inspect()['identity'] == initial['source']['identity']
        assert gate.inspect()['muted'] is True
        assert all(p.poll() is None for p in processes)
        assert producer.failure is None
