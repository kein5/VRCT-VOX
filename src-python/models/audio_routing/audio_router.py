"""P1 output router. Does not capture, mix, or route unconverted microphones."""
import sys
from time import monotonic_ns

from models.tts.speechcpp_tts import SpeechError
from .gc_guard import defer_cyclic_gc


def enumerate_outputs():
    if sys.platform == "win32":
        from .devices_windows import enumerate_outputs as enumerate_windows
        return enumerate_windows()
    if sys.platform.startswith("linux"):
        from .devices_pipewire import enumerate_outputs as enumerate_pipewire
        return enumerate_pipewire()
    raise SpeechError("unsupported_platform")


def open_output(device, rate, channels):
    if not device:
        raise SpeechError("output_not_selected")
    if sys.platform == "win32":
        from .devices_windows import WindowsOutput
        return WindowsOutput(device, rate, channels)
    if sys.platform.startswith("linux"):
        from .devices_pipewire import PipeWireOutput
        return PipeWireOutput(device, rate, channels)
    raise SpeechError("unsupported_platform")


class AudioRouter:
    def __init__(self, output_factory=open_output):
        self.output_factory = output_factory

    def play(self, frames, device, token, on_first_audio):
        # A full cyclic collection can hold the GIL longer than the bounded
        # native output queue, starving playback even while PCM is available.
        with defer_cyclic_gc():
            self._play(frames, device, token, on_first_audio)

    def _play(self, frames, device, token, on_first_audio):
        sink = None
        stream_format = None
        first = True
        success = False
        try:
            for frame in frames:
                token.check()
                current_format = (frame.sample_rate, frame.channels)
                if stream_format is not None and stream_format != current_format:
                    raise SpeechError("format_changed")
                if sink is None:
                    sink = self.output_factory(device, *current_format)
                    stream_format = current_format
                # <=10 ms of PCM per write; no inference or HTTP on callbacks.
                block = max(1, frame.sample_rate // 100) * frame.channels * 2
                for offset in range(0, len(frame.pcm), block):
                    token.check()
                    pcm = frame.pcm[offset:offset + block]
                    sink.write(pcm, token)
                    if first and any(pcm):
                        # Native nonblocking adapters commit at their write
                        # boundary; other outputs confirm when write returns.
                        token.begin_playback()
                        first = False
                        on_first_audio(monotonic_ns(), frame.sample_rate)
            token.check()
            success = True
        finally:
            if sink is not None:
                sink.close(drain=success, token=token)
