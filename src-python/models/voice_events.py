"""Immutable events; no dependency on VRCT's Windows runtime."""
from dataclasses import dataclass, field
from time import monotonic_ns


@dataclass(frozen=True)
class SpeechMessageEvent:
    event_id: str
    source: str
    original_text: str
    translated_text: str | None = None
    source_language: str | None = None
    target_language: str | None = None
    utterance_id: str | None = None
    revision: int = 0
    is_final: bool = True
    timestamp_ns: int = field(default_factory=monotonic_ns)


@dataclass(frozen=True)
class AudioFrame:
    """Interleaved signed 16-bit little-endian PCM, never a WAV container."""
    pcm: bytes
    sample_rate: int
    channels: int = 1

    def __post_init__(self):
        if not 8000 <= self.sample_rate <= 192000 or self.channels not in (1, 2):
            raise ValueError("Unsupported PCM format")
        if len(self.pcm) % (2 * self.channels):
            raise ValueError("Incomplete PCM frame")
