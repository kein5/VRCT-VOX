"""One-shot Linux route diagnostics. Stop VRCT before using mute/resume here.

The running application's watchdog owns its gate and will revoke outside changes.
Use its UI for normal operation. This CLI does not provide ongoing supervision.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src-python'))
from models.audio_routing.mute_state import MuteState  # noqa: E402
from models.audio_routing.pipewire_gate import PipeWireGate  # noqa: E402


def control(action, *, gate, store):
    state = gate.inspect()
    if action == 'mute':
        # Native silence must still be attempted if durable storage is unavailable.
        try:
            store.write(True)
        finally:
            state = gate.set_muted(True, state['identity'])
    elif action == 'resume':
        store.read()  # Invalid durable state must be repaired by mute first.
        try:
            state = gate.set_muted(False, state['identity'])
            store.write(False)
        except Exception:
            gate.set_muted(True, state['identity'])
            raise
    elif action != 'status':
        raise ValueError('invalid_action')
    return {'observed_muted': state['muted'], 'stored_muted': store.read(),
            'identity': state['identity'], 'supervised': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'mute', 'resume'))
    parser.add_argument('--state-file', type=Path, required=True,
                        help='voice_mute_state.json next to the application config.json')
    args = parser.parse_args()
    try:
        result = control(args.action, gate=PipeWireGate(), store=MuteState(args.state_file))
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, RuntimeError) else 'route_control_failed',
                          'confirmed': False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
