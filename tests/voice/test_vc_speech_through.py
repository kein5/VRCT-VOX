"""Speech through the conversion (ADR-007): it replaces the microphone, part for part."""
import time

import pytest

from models.transcription.realtime_audio import CapturedAudio
from models.voice_conversion import process as vp
from models.voice_conversion import protocol as p
from models.voice_events import AudioFrame

MIC = b"\x11\x00" * (vp.SPEECH_PART // 2)
SPEECH = b"\x22\x00" * (vp.SPEECH_PART // 2)
SILENCE = bytes(vp.SPEECH_PART)


@pytest.fixture
def process():
    proc = vp.VCProcess(engine="rvc", output="test-device")
    proc._requested = True
    proc._clock = [time.monotonic_ns() - 10_000_000_000]
    return proc


def capture(proc, parts=4):
    """Feed `parts` 20 ms microphone parts; return the blocks queued (pcm, speech)."""
    for _ in range(parts):
        proc._clock[0] += 20_000_000
        assert proc._audio(CapturedAudio(AudioFrame(MIC, p.RATE, 1), proc._clock[0]))
    blocks = []
    while not proc._queue.empty():
        _, pcm, speech = proc._queue.get_nowait()
        blocks.append((pcm, speech))
    return blocks


def parts(pcm):
    return [pcm[i:i + vp.SPEECH_PART] for i in range(0, len(pcm), vp.SPEECH_PART)]


def test_without_speech_the_microphone_is_converted_as_before(process):
    [(pcm, speech)] = capture(process)
    assert parts(pcm) == [MIC] * 4 and speech is False


def test_speech_replaces_the_microphone_then_the_microphone_returns(process):
    assert process.speech_chunk(SPEECH * 4) and process.speech_chunk(SPEECH * 2)
    process.speech_end()
    first, second = capture(process, 8)
    assert parts(first[0]) == [SPEECH] * 4 and first[1] is True
    # Two parts of speech are left; the block they end in is still marked as speech.
    assert parts(second[0]) == [SPEECH, SPEECH, MIC, MIC] and second[1] is True
    [(third, speech)] = capture(process)
    assert parts(third) == [MIC] * 4 and speech is False


def test_a_gap_inside_an_utterance_is_silence_never_the_microphone(process):
    assert process.speech_chunk(SPEECH)
    [(pcm, speech)] = capture(process)
    assert parts(pcm) == [SPEECH, SILENCE, SILENCE, SILENCE] and speech is True


def test_cancel_drops_waiting_speech_at_the_next_part(process):
    assert process.speech_chunk(SPEECH * 4) and process.speech_chunk(SPEECH * 4)
    capture(process, 2)
    process.speech_cancel()
    [(pcm, speech)] = capture(process, 2)
    assert parts(pcm) == [SPEECH, SPEECH, MIC, MIC]
    [(pcm, speech)] = capture(process)
    assert parts(pcm) == [MIC] * 4 and speech is False


def test_speech_is_bounded_and_refused_once_stopped(process):
    assert process.speech_chunk(b"\0\0" * (p.PCM_BYTES // 2))
    while process.speech_chunk(b"\0\0" * (p.PCM_BYTES // 2)):
        pass
    assert len(process._speech) == vp.SPEECH_LIMIT
    process.speech_cancel()
    process._requested = False
    assert process.speech_chunk(SPEECH) is False
    for bad in (b"", b"\0", b"\0" * (p.PCM_BYTES + 2), "text"):
        with pytest.raises(ValueError):
            process.speech_chunk(bad)


def test_suppression_silences_the_microphone_blocks_and_lets_speech_through(process):
    process.set_direct_suppressed(True)
    process._monitor_muted = False
    assert process._audible(b"\1\2", speech=False) == b"\0\0"
    assert process._audible(b"\1\2", speech=True) == b"\1\2"
    # Mute stops everything, the converted speech included.
    process._monitor_muted = True
    assert process._audible(b"\1\2", speech=True) == b"\0\0"


def test_on_a_managed_route_suppression_is_done_here_and_mute_stays_with_the_gate():
    managed = vp.VCProcess(engine="rvc")
    managed._monitor_muted = True
    assert managed._audible(b"\1\2", speech=True) == b"\1\2"  # the OS gate mutes this route
    managed.set_direct_suppressed(True)
    assert managed._audible(b"\1\2", speech=False) == b"\0\0"
    assert managed._audible(b"\1\2", speech=True) == b"\1\2"
