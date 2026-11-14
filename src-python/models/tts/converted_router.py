"""Play speech through the running voice conversion instead of an output device (ADR-007).

The TTS worker hands the same frames it would play. They are made 48 kHz mono s16le,
the conversion's input, and replace the microphone while they last. The conversion's
own output, mute and monitor then carry them, so this router opens no device.
"""
from models.tts.speechcpp_tts import SpeechError

RATE = 48000


def _mono(frame):
    if frame.channels == 1:
        return frame.pcm
    import numpy as np
    samples = np.frombuffer(frame.pcm, dtype="<i2").reshape(-1, frame.channels).astype(np.int32)
    return samples.mean(axis=1).astype("<i2").tobytes()


def to_conversion_rate(frames):
    """48 kHz mono s16le bytes for each speech frame, one resampler for the stream."""
    stream = None
    rate = None
    for frame in frames:
        if rate is None:
            rate = frame.sample_rate
        elif frame.sample_rate != rate:
            raise SpeechError("format_changed")
        pcm = _mono(frame)
        if rate == RATE:
            if pcm:
                yield pcm
            continue
        import numpy as np
        if stream is None:
            import soxr
            stream = soxr.ResampleStream(rate, RATE, 1, dtype="int16", quality="HQ")
        out = stream.resample_chunk(np.frombuffer(pcm, dtype="<i2"))
        if len(out):
            yield out.astype("<i2").tobytes()
    if stream is not None:
        import numpy as np
        out = stream.resample_chunk(np.zeros(0, dtype="<i2"), last=True)
        if len(out):
            yield out.astype("<i2").tobytes()


class ConvertedSpeechRouter:
    def __init__(self, direct_voice):
        self.direct_voice = direct_voice

    def available(self):
        return self.direct_voice.speaking_available()

    def play(self, frames, device, token, on_first_audio, monitor=None):
        # The device is the conversion's; a TTS monitor would play the unconverted voice.
        del device, monitor

        def first(timestamp, rate):
            token.begin_playback()
            on_first_audio(timestamp, rate)

        try:
            self.direct_voice.speak(to_conversion_rate(frames), token, first)
        except RuntimeError as exc:
            if str(exc) == "vc_speech_unavailable":
                raise SpeechError("conversion_unavailable") from None
            raise
