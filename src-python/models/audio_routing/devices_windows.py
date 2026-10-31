"""PyAudioWPatch playback only. Never use the OS default device."""
import json

from models.tts.speechcpp_tts import SpeechError


def _identity(pa, info):
    host = pa.get_host_api_info_by_index(int(info["hostApi"]))["name"]
    return json.dumps([host, info["name"]], ensure_ascii=False)


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


class WindowsOutput:
    def __init__(self, device, rate, channels, *, strict_underflow=True):
        import pyaudiowpatch as audio
        # A monitor tolerates a stalled server's gap; the virtual mic reports it.
        self.strict_underflow = strict_underflow
        self.pa = audio.PyAudio()
        self.stream = None
        try:
            matches = [i for i in range(self.pa.get_device_count())
                       if self.pa.get_device_info_by_index(i)["maxOutputChannels"] >= channels
                       and _identity(self.pa, self.pa.get_device_info_by_index(i)) == device]
            if len(matches) != 1:
                raise SpeechError("output_missing_or_ambiguous")
            self.stream = self.pa.open(format=audio.paInt16, channels=channels, rate=rate,
                                       output=True, output_device_index=matches[0],
                                       frames_per_buffer=max(1, rate // 100))
        except Exception:
            self.pa.terminate()
            raise

    def write(self, pcm, token):
        token.check()
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
