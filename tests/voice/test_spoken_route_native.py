"""Synthetic private PipeWire only; no host microphone or VRChat capture."""
import json
from pathlib import Path
import subprocess
import sys
from time import monotonic_ns

import pytest

from models.audio_routing.managed_route import VoiceRoute
from models.audio_routing.mute_state import MuteState
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE, TTS_SINK, VC_SINK
from models.tts.tts_scheduler import VoiceEventBus
from test_source_bridge_native import compile_helper
from tools.voice_acceptance import private_graph, wait_for
from tools.voice_b_poc import Producer, ToneCapture, settled

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'config/pipewire/90-vrct-managed.conf'
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux PipeWire native gate')


def test_direct_gate_targets_only_bound_vc_sink(tmp_path):
    helper = compile_helper(tmp_path, 'native/voice-gate/main.c', pipewire=True)
    with private_graph(config_fragment=CONFIG):
        gate = PipeWireGate(helper)
        pair = gate.inspect_pair()
        identity = pair['direct']['identity']
        assert gate.set_direct_muted(True, identity)['muted']
        assert gate.inspect()['muted']  # Main source is independently boot-muted.
        for cookie, serial, selector in (
            (identity[0] + 1, identity[1], 'vc'),
            (identity[0], identity[1] + 1, 'vc'),
            (identity[0], identity[1], 'vrct.managed.tts'),
        ):
            result = subprocess.run([str(helper), str(cookie), str(serial), '0', selector], timeout=3)
            assert result.returncode != 0
            assert gate.inspect_pair()['direct']['muted']
        assert gate.set_direct_muted(False, identity)['muted'] is False
        assert gate.inspect()['muted'] is True


def test_private_direct_suppression_keeps_tts_audible_and_requires_resume(tmp_path):
    helper = compile_helper(tmp_path, 'native/voice-gate/main.c', pipewire=True)
    rows = []
    with private_graph(config_fragment=CONFIG) as stack:
        gate = PipeWireGate(helper)
        bus = VoiceEventBus()
        stack.callback(bus.close)
        control = VoiceRoute(bus, gate=gate, store=MuteState(tmp_path / 'mute.json'))
        stack.callback(control.close)
        control.configure(True, suppress_direct=True)
        def confirmed():
            wait_for(lambda: control.status()['ready'] and not control.status()['pending'],
                     code='route_not_ready')
        confirmed()
        Producer(stack, VC_SINK, 440)
        Producer(stack, TTS_SINK, 880)
        capture = ToneCapture(stack, SOURCE)
        for policy, present, absent in ((True, (880,), (440,)), (False, (440, 880), ())):
            control.configure(True, suppress_direct=policy)
            confirmed()
            settled(capture, monotonic_ns(), 'policy_transition_not_silent', silent=True)
            start = monotonic_ns()
            control.resume()
            confirmed()
            first = settled(capture, start, 'wrong_branch_audio', present=present, absent=absent)
            rows.append({'suppress_direct': policy, 'resume_call_ns': start,
                         'first_qualifying_private_read_ns': first})
        # An external branch change must revoke the open main gate.
        gate.set_direct_muted(True, gate.inspect_pair()['direct']['identity'])
        wait_for(lambda: control.status()['requested_muted'], code='drift_not_revoked')
        confirmed()
        settled(capture, monotonic_ns(), 'drift_not_silent', silent=True)
        assert gate.inspect_pair()['direct']['muted'] is False
        assert gate.inspect()['muted'] and bus.status()['muted']
        report = {'boundary': 'resume call to first qualifying private 20ms read; 2s hold',
                  'rows': rows, 'capture': capture.snapshot(),
                  'physical_microphone_captured': False, 'vrchat_verified': False}
        (tmp_path / 'spoken-route.json').write_text(json.dumps(report, indent=2))
