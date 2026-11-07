"""PyAudioWPatch devices. Never use the OS default device for TTS or converted voice."""
import json
import re
from zlib import crc32

from models.tts.speechcpp_tts import SpeechError
from .source_bridge import Endpoint

# Drivers that connect a playback device straight to a recording device.
_CABLE_DRIVERS = ('cable', 'virtual', 'steam streaming', 'voicemeeter')


def prepare_audio_thread():
    """Call on a thread that opens a stream, before PyAudio.

    PortAudio sets up COM only on the thread that first opens it. A second owner
    on another thread then fails to start WASAPI with "Unanticipated host error".
    """
    import ctypes
    if hasattr(ctypes, 'windll'):
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # Already set up is not an error.


def _identity(pa, info):
    host = pa.get_host_api_info_by_index(int(info["hostApi"]))["name"]
    return json.dumps([host, info["name"]], ensure_ascii=False)


def device_name(identity):
    """The device name inside an identity, or the text itself if it is not one."""
    try:
        value = json.loads(identity)
        return value[1] if isinstance(value, list) and len(value) == 2 else identity
    except (TypeError, ValueError):
        return identity


def _driver(name):
    match = re.search(r'\(([^()]*)\)?\s*$', name)
    return match[1].strip().lower() if match else ''


def same_virtual_cable(first, second):
    """Whether audio written to one device comes back out of the other.

    A cable's two ends share a driver name, and MME cuts names at 31 characters.
    A real sound card's microphone and speakers share one too, so only known
    virtual drivers count.
    """
    one, other = _driver(device_name(first)), _driver(device_name(second))
    return (bool(one) and bool(other) and (one.startswith(other) or other.startswith(one))
            and any(word in one for word in _CABLE_DRIVERS))


def is_virtual_cable(identity):
    return any(word in _driver(device_name(identity)) for word in _CABLE_DRIVERS)


def enumerate_outputs():
    import pyaudiowpatch as audio
    pa = audio.PyAudio()
    try:
        result = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxOutputChannels"] > 0 and not info.get("isLoopbackDevice", False):
                result.append({"id": _identity(pa, info), "label": _identity(pa, info)})
        return result
    finally:
        pa.terminate()


def default_output():
    """Identity of the OS default output. Monitor only: TTS never uses a default."""
    import pyaudiowpatch as audio
    pa = audio.PyAudio()
    try:
        try:
            info = pa.get_default_output_device_info()
        except (OSError, LookupError) as exc:
            raise SpeechError("output_missing") from exc
        return _identity(pa, info)
    finally:
        pa.terminate()


def _endpoint(identity, source):
    # cookie and serial only have to be stable: a Windows device has no graph
    # identity, and its index moves when another device appears.
    return Endpoint(crc32(identity.encode('utf-8')), 0, identity,
                    'Audio/Source' if source == 'mic' else 'Audio/Sink')


def _wasapi(pa, audio):
    return pa.get_host_api_info_by_type(audio.paWASAPI)


def _endpoint_rows(pa, audio, source):
    host = _wasapi(pa, audio)['index']
    channels = 'maxInputChannels' if source == 'mic' else 'maxOutputChannels'
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if int(info['hostApi']) == host and info[channels] > 0 and not info.get('isLoopbackDevice', False):
            yield info


def enumerate_endpoints(source):
    """WASAPI microphones or speakers. Other host APIs repeat the same hardware."""
    import pyaudiowpatch as audio
    pa = audio.PyAudio()
    try:
        return [{'endpoint': _endpoint(_identity(pa, info), source), 'label': info['name']}
                for info in _endpoint_rows(pa, audio, source)]
    finally:
        pa.terminate()


def default_endpoint(source):
    import pyaudiowpatch as audio
    pa = audio.PyAudio()
    try:
        host = _wasapi(pa, audio)
        index = host['defaultInputDevice' if source == 'mic' else 'defaultOutputDevice']
        if index < 0:
            raise ValueError('realtime_default_endpoint_missing')
        identity = _identity(pa, pa.get_device_info_by_index(index))
    except (OSError, LookupError):
        raise ValueError('realtime_default_endpoint_missing') from None
    finally:
        pa.terminate()
    # Speaker capture hears the room's output either way; a cable as the default
    # microphone would transcribe or convert VRCT-VOX's own speech.
    if source == 'mic' and is_virtual_cable(identity):
        raise ValueError('realtime_default_endpoint_feedback')
    return _endpoint(identity, source)


def capture_device(pa, audio, endpoint, source):
    """Device info to open for an endpoint; a speaker is read through its loopback twin."""
    matches = [info for info in _endpoint_rows(pa, audio, source)
               if _identity(pa, info) == endpoint.name]
    if len(matches) != 1:
        raise LookupError('endpoint_missing')
    return matches[0] if source == 'mic' else pa.get_wasapi_loopback_analogue_by_dict(matches[0])


class WindowsOutput:
    def __init__(self, device, rate, channels, *, strict_underflow=True):
        import pyaudiowpatch as audio
        prepare_audio_thread()
        # A monitor tolerates a stalled server's gap; the virtual mic reports it.
        self.strict_underflow = strict_underflow
        self.pa = audio.PyAudio()
        self.stream = None
        self.channels = self.device_channels = channels
        self._resampler = None
        try:
            matches = [i for i in range(self.pa.get_device_count())
                       if self.pa.get_device_info_by_index(i)["maxOutputChannels"] >= channels
                       and _identity(self.pa, self.pa.get_device_info_by_index(i)) == device]
            if len(matches) != 1:
                raise SpeechError("output_missing_or_ambiguous")
            # PortAudio's own mono path garbles WASAPI playback: a 440 Hz tone
            # read back at about 840 Hz. Hand it stereo instead.
            if channels == 1 and self.pa.get_device_info_by_index(matches[0])["maxOutputChannels"] >= 2:
                self.device_channels = 2
            try:
                self._open(audio, matches[0], rate)
            except OSError:
                # WASAPI shared mode opens only at the device's mix rate, while
                # speech arrives at the model's. Convert rather than fail.
                native = int(self.pa.get_device_info_by_index(matches[0])["defaultSampleRate"])
                if native == rate:
                    raise
                import soxr
                self._resampler = soxr.ResampleStream(rate, native, channels, dtype="int16")
                self._open(audio, matches[0], native)
        except Exception:
            self.pa.terminate()
            raise

    def _open(self, audio, index, rate):
        self.stream = self.pa.open(format=audio.paInt16, channels=self.device_channels, rate=rate,
                                   output=True, output_device_index=index,
                                   frames_per_buffer=max(1, rate // 100))

    def _convert(self, pcm):
        import numpy as np
        samples = np.frombuffer(pcm, dtype="<i2")
        if self._resampler is not None:
            if self.channels > 1:
                samples = samples.reshape(-1, self.channels)
            samples = self._resampler.resample_chunk(samples).reshape(-1)
        if self.device_channels != self.channels:
            samples = np.repeat(samples, self.device_channels)
        return samples.astype("<i2").tobytes()

    def write(self, pcm, token):
        token.check()
        if self._resampler is not None or self.device_channels != self.channels:
            pcm = self._convert(pcm)
            if not pcm:
                return
        self.stream.write(pcm, exception_on_underflow=self.strict_underflow)

    def close(self, *, drain, token):
        # PortAudio owns the final hardware buffer. Immediate device abort and
        # hot-unplug timing must be measured on WASAPI; do not promise zero ms.
        try:
            try:
                if drain and not token.is_set():
                    self.stream.stop_stream()
            finally:
                self.stream.close()
        finally:
            self.pa.terminate()
