"""Test only: read the 'microphone' from a silent virtual output's loopback instead of a real mic."""
import os
import sys

# The conversion workers inherit PYTHONPATH. This hook must not run inside them.
_in_worker = any(arg.startswith('integrations.') for arg in sys.orig_argv)

_probe = None if _in_worker else os.environ.get('VOX_VC_PROBE')
if _probe:
    # The block timing normally reaches the log only when the conversion stops.
    import json as _json
    import threading as _threading
    import time as _time
    from models.voice_conversion import process as _process

    _init = _process.VCProcess.__init__

    def _report(owner):
        while True:
            _time.sleep(5)
            try:
                row = dict(at=round(_time.time(), 1), blocks=owner._blocks, late=sum(owner._late), window=len(owner._late),
                           age=_process._summary_ms(list(owner._ages)), round_trip=_process._summary_ms(list(owner._rounds)))
            except RuntimeError:  # A deque changed while it was copied.
                continue
            with open(_probe, 'a', encoding='utf-8') as stream:
                stream.write(_json.dumps(row) + '\n')

    def _init_with_probe(self, *args, **kwargs):
        _init(self, *args, **kwargs)
        _threading.Thread(target=_report, args=(self,), daemon=True).start()

    _process.VCProcess.__init__ = _init_with_probe

_device = None if _in_worker else os.environ.get('VOX_MIC_AS_LOOPBACK')
if _device:
    import models.audio_routing.devices_windows as devices

    _real = devices.capture_device

    def capture_device(pa, audio, endpoint, source):
        if source == 'mic':
            for info in devices._endpoint_rows(pa, audio, 'speaker'):
                if devices._identity(pa, info) == _device:
                    return pa.get_wasapi_loopback_analogue_by_dict(info)
            raise LookupError('endpoint_missing')
        return _real(pa, audio, endpoint, source)

    devices.capture_device = capture_device

    import pyaudiowpatch as _audio
    import sys
    import traceback
    _open = _audio.PyAudio.open

    def logged_open(self, *args, **kwargs):
        try:
            value = _open(self, *args, **kwargs)
            print('open ok', {k: v for k, v in kwargs.items() if k != 'stream_callback'}, file=sys.stderr, flush=True)
            return value
        except Exception:
            print('open failed', {k: v for k, v in kwargs.items() if k != 'stream_callback'}, file=sys.stderr, flush=True)
            traceback.print_exc()
            raise

    _audio.PyAudio.open = logged_open
