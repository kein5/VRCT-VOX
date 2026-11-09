"""Test only: read the 'microphone' from a silent virtual output's loopback instead of a real mic."""
import os

_device = os.environ.get('VOX_MIC_AS_LOOPBACK')
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
