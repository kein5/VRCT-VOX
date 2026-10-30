"""Experimental offline PCM checks; envelope matching is not a speech-quality metric.

Input: little-endian signed 16-bit mono PCM. The caller must separately verify
capture liveness, node identity, output isolation and complete observation windows.
"""
import argparse
from array import array
import json
import math
from pathlib import Path
import sys
import wave


def samples(pcm):
    if len(pcm) % 2:
        raise ValueError('partial_sample')
    result = array('h', pcm)
    if sys.byteorder != 'little':
        result.byteswap()
    return result


def envelope(values, frame):
    return [math.sqrt(sum(v * v for v in values[i:i + frame]) / frame)
            for i in range(0, len(values) - frame + 1, frame)]


def compare_pcm(reference, observed, rate, *, threshold=0.8):
    if rate < 100 or not 0 < threshold <= 1:
        raise ValueError('invalid_analysis_settings')
    try:
        ref, obs = samples(reference), samples(observed)
    except ValueError:
        return {'verdict': 'inconclusive', 'reason': 'partial_sample'}
    if len(ref) < rate // 2 or len(obs) < len(ref):
        return {'verdict': 'inconclusive', 'reason': 'insufficient_audio'}
    frame = rate // 50  # 20 ms envelope, not latency precision.
    pattern, signal = envelope(ref, frame), envelope(obs, frame)
    mean = sum(pattern) / len(pattern)
    centered = [v - mean for v in pattern]
    norm = math.sqrt(sum(v * v for v in centered))
    if mean < 8 or norm < 1:
        return {'verdict': 'inconclusive', 'reason': 'uninformative_reference'}
    candidates = []
    best = 0.0
    n = len(pattern)
    for start in range(len(signal) - n + 1):
        window = signal[start:start + n]
        avg = sum(window) / n
        denom = math.sqrt(sum((v - avg) ** 2 for v in window)) * norm
        score = sum(a * (b - avg) for a, b in zip(centered, window)) / denom if denom else 0
        if avg < 8:
            score = 0
        best = max(best, score)
        if score >= threshold:
            candidates.append((score, start))
    peaks = []
    for score, start in sorted(candidates, reverse=True):
        if all(abs(start - existing[1]) >= n * .8 for existing in peaks):
            peaks.append((score, start))
    return {'verdict': 'pass' if len(peaks) == 1 else 'fail', 'occurrences': len(peaks),
            'best_envelope_correlation': best, 'threshold': threshold,
            'matches': [{'offset_seconds': start * frame / rate, 'score': score}
                        for score, start in sorted(peaks, key=lambda p: p[1])],
            'observed_seconds': len(obs) / rate,
            'boundary': 'saved_pcm_envelope_only', 'perceptual_quality_measured': False}


def silence_pcm(observed, rate, *, minimum_seconds=2, peak_limit=8):
    if rate <= 0 or minimum_seconds <= 0 or peak_limit < 0:
        raise ValueError('invalid_analysis_settings')
    try:
        values = samples(observed)
    except ValueError:
        return {'verdict': 'inconclusive', 'reason': 'partial_sample'}
    if len(values) < rate * minimum_seconds:
        return {'verdict': 'inconclusive', 'reason': 'insufficient_audio'}
    peak = max(abs(v) for v in values)
    return {'verdict': 'pass' if peak <= peak_limit else 'fail', 'peak_s16': peak,
            'observed_seconds': len(values) / rate, 'peak_limit_s16': peak_limit}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True, help='s16 mono WAV')
    parser.add_argument('--observed', type=Path, required=True, help='s16le mono raw PCM')
    parser.add_argument('--threshold', type=float, default=.8)
    args = parser.parse_args()
    with wave.open(str(args.reference), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            parser.error('reference must be signed 16-bit mono')
        result = compare_pcm(wav.readframes(wav.getnframes()), args.observed.read_bytes(),
                             wav.getframerate(), threshold=args.threshold)
    print(json.dumps(result, indent=2))
    return 0 if result['verdict'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
