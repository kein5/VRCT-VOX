"""Opt-in private PipeWire integration: HTTP TTS failure preserves synthetic VC.

Run with uv run --no-project python tests/voice/listener_mix_poc.py --output DIR.
Requires the test dependencies and built native gate. No model or microphone.
Kept outside pytest discovery because it starts real audio daemons.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src-python'))
from test_tts_listener_failure import buffered_server  # noqa: E402
from models.audio_routing.managed_route import VoiceRoute  # noqa: E402
from models.audio_routing.mute_state import MuteState  # noqa: E402
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE, VC_SINK  # noqa: E402
from models.tts.settings import VoiceSettings  # noqa: E402
from models.tts.tts_scheduler import VoiceEventBus  # noqa: E402
from models.voice_events import SpeechMessageEvent  # noqa: E402
from tools.managed_vrchat_probe import require_continuous_capture  # noqa: E402
from tools.voice_acceptance import idle, private_graph, wait_for  # noqa: E402
from tools.voice_b_poc import Producer, ToneCapture, ready, settled, tone  # noqa: E402
from tools.voice_route_acceptance import confirmed  # noqa: E402


def exercise(output, report):
    with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf') as stack, \
            buffered_server(pcm=tone(880) * 100) as (url, sent, _finish, stop):
        gate = PipeWireGate()
        initial = gate.inspect()
        if initial['muted'] is not True:
            raise RuntimeError('initial_gate_not_muted')
        bus = VoiceEventBus(VoiceSettings(mode='original', routing='managed', japanese_url=url))
        stack.callback(bus.close)
        route = VoiceRoute(bus, gate=gate, store=MuteState(output / 'state.json'))
        stack.callback(route.close)
        route.configure(True)
        confirmed(route)
        vc = Producer(stack, VC_SINK, 440)
        capture = ToneCapture(stack, SOURCE)
        settled(capture, time.monotonic_ns(), 'initial_not_silent', silent=True)
        route.resume()
        confirmed(route)
        ready(capture, 440)
        if not bus.publish(SpeechMessageEvent('mixed', 'chat', 'synthetic', source_language='ja')):
            raise RuntimeError('tts_rejected')
        ready(capture, 440, 880)
        if not sent.wait(1):
            raise RuntimeError('backlog_not_sent')
        before = capture.snapshot()
        started = time.monotonic_ns()
        stop()
        after = wait_for(lambda: idle(bus), timeout=1, code='failed_tts_still_active')
        if after['errors'] != 1 or after['last_error'] != 'server_unavailable':
            raise RuntimeError('listener_loss_not_detected')
        first = settled(capture, started, 'tts_tail_or_vc_missing', present=(440,), absent=(880,))
        current = capture.snapshot()
        state = gate.inspect()
        if (state['identity'] != initial['identity'] or state['muted'] or vc.failure
                or current['detected_frames']['440'] - before['detected_frames']['440']
                != current['frames'] - before['frames']):
            raise RuntimeError('vc_interrupted_or_gate_changed')
        report.update(command_ns=started, first_tts_absent_read_ns=first,
                      command_to_tts_absent_ms=(first - started) / 1e6,
                      before=before, after=current, bus_after=after, gate_after=state,
                      vc_present_in_all_frames=True)
        require_continuous_capture(current)
        route.mute()
        confirmed(route)
        settled(capture, time.monotonic_ns(), 'explicit_global_mute_failed', silent=True)
        report['final_capture'] = capture.snapshot()
        require_continuous_capture(report['final_capture'])
        report['explicit_global_mute_silent'] = True
        if not route.close() or not bus.close():
            raise RuntimeError('control_shutdown_failed')
    if report['command_to_tts_absent_ms'] > 250:
        raise RuntimeError('fault_silence_budget_exceeded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'failed', 'real_tts_model': False, 'real_vc_model': False,
              'physical_microphone': False, 'environment': 'private_pipewire',
              'tts_tone_hz': 880, 'vc_tone_hz': 440, 'source_read_frame_ms': 20,
              'tone_threshold_s16': 400, 'silence_peak_threshold_s16': 64,
              'silence_budget_ms': 250}
    try:
        exercise(args.output, report)
        report['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as exc:
        report['failure'] = str(exc) or type(exc).__name__
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    return int(report['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
