"""Transcribe an explicitly supplied local PCM WAV; report metadata, not text."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import monotonic_ns
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src-python'))
from models.transcription.speechcpp_asr import SpeechCppASR  # noqa: E402
from models.voice_events import AudioFrame  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--language', default='auto')
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError('new_report_path_required')
    with wave.open(str(args.input), 'rb') as source:
        rate, channels, count = source.getframerate(), source.getnchannels(), source.getnframes()
        if source.getsampwidth() != 2 or not 0 < count <= rate * 60:
            raise ValueError('requires_1_to_60_seconds_s16_pcm')
        pcm = source.readframes(count)
        if len(pcm) != count * channels * 2:
            raise ValueError('truncated_wav')
    audio = AudioFrame(pcm, rate, channels)
    start = monotonic_ns()
    result = SpeechCppASR(args.url).transcribe(audio, args.model, args.language)
    elapsed_ms = (monotonic_ns() - start) / 1e6
    report = {'scope': 'REST including model preflight; no capture/VRChat',
        'model': result.model, 'requested_language': result.requested_language,
        'sample_rate': rate, 'channels': channels, 'duration_s': count / rate,
        'pcm_sha256': hashlib.sha256(pcm).hexdigest(), 'characters': len(result.text),
        'elapsed_ms': elapsed_ms, 'status': 'complete'}
    with args.report.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
