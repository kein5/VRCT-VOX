//! Pitch: the extractor boundary, the RMVPE front and back ends, and the conversion of
//! an F0 track into what the synthesizer takes (specification section 5).

use std::sync::Arc;

use rustfft::num_complex::Complex32;
use rustfft::{Fft, FftPlanner};

use crate::error::Result;

/// Frames per second of every pitch track in this crate (160 samples at 16 kHz).
pub const FRAME_RATE: usize = 100;
/// Samples per pitch frame at 16 kHz.
pub const HOP: usize = 160;

/// A pitch extractor. RMVPE is the required one; others can stand in behind this trait.
pub trait F0Estimator {
    /// F0 in Hz per 10 ms frame of 16 kHz audio, `0.0` where unvoiced.
    /// Returns `audio.len() / 160 + 1` frames.
    fn estimate(&mut self, audio: &[f32]) -> Result<Vec<f32>>;
}

const N_FFT: usize = 1024;
const N_MELS: usize = 128;
const MEL_FMIN: f64 = 30.0;
const MEL_FMAX: f64 = 8000.0;
const LOG_FLOOR: f32 = 1e-5;
/// Salience bins of the network output and their spacing.
pub const SALIENCE_BINS: usize = 360;
const CENTS_PER_BIN: f64 = 20.0;
const CENTS_OFFSET: f64 = 1997.379_408_437_619_1;

/// The log-mel front end RMVPE was trained with: 1024-point FFT, 10 ms hop, 128 HTK-scale
/// triangular filters between 30 Hz and 8 kHz with area normalisation.
pub struct MelSpectrogram {
    fft: Arc<dyn Fft<f32>>,
    window: Vec<f32>,
    /// `N_MELS` rows of `N_FFT / 2 + 1` weights, with the first and last non-zero bin.
    filters: Vec<(usize, Vec<f32>)>,
}

impl Default for MelSpectrogram {
    fn default() -> Self {
        Self::new()
    }
}

impl MelSpectrogram {
    pub fn new() -> Self {
        let fft = FftPlanner::<f32>::new().plan_fft_forward(N_FFT);
        // Periodic Hann window.
        let window = (0..N_FFT).map(|n| (0.5 - 0.5 * (2.0 * std::f64::consts::PI * n as f64 / N_FFT as f64).cos()) as f32).collect();
        MelSpectrogram { fft, window, filters: mel_filters(16_000.0) }
    }

    /// Log-mel spectrogram, row-major `[N_MELS][frames]`, with `frames = len / 160 + 1`.
    /// The signal is reflect-padded by half a window so frames are centred.
    pub fn compute(&self, audio: &[f32]) -> (Vec<f32>, usize) {
        let frames = audio.len() / HOP + 1;
        let half = N_FFT / 2;
        let last = audio.len() as isize - 1;
        // Reflect without repeating the edge sample; fold again if the signal is shorter than the padding.
        let sample = |index: isize| -> f32 {
            if last <= 0 {
                return audio.first().copied().unwrap_or(0.0);
            }
            let period = 2 * last;
            let folded = index.rem_euclid(period);
            audio[if folded > last { period - folded } else { folded } as usize]
        };
        let bins = half + 1;
        let mut mel = vec![0.0f32; N_MELS * frames];
        let mut buffer = vec![Complex32::new(0.0, 0.0); N_FFT];
        let mut magnitude = vec![0.0f32; bins];
        for frame in 0..frames {
            let start = (frame * HOP) as isize - half as isize;
            for (n, slot) in buffer.iter_mut().enumerate() {
                *slot = Complex32::new(sample(start + n as isize) * self.window[n], 0.0);
            }
            self.fft.process(&mut buffer);
            for (bin, slot) in magnitude.iter_mut().enumerate() {
                *slot = buffer[bin].norm();
            }
            for (band, (first, weights)) in self.filters.iter().enumerate() {
                let energy: f32 = weights.iter().zip(&magnitude[*first..]).map(|(w, m)| w * m).sum();
                mel[band * frames + frame] = energy.max(LOG_FLOOR).ln();
            }
        }
        (mel, frames)
    }
}

fn mel_filters(sample_rate: f64) -> Vec<(usize, Vec<f32>)> {
    let to_mel = |hz: f64| 2595.0 * (1.0 + hz / 700.0).log10();
    let to_hz = |mel: f64| 700.0 * (10f64.powf(mel / 2595.0) - 1.0);
    let (low, high) = (to_mel(MEL_FMIN), to_mel(MEL_FMAX));
    let edges: Vec<f64> = (0..N_MELS + 2).map(|i| to_hz(low + (high - low) * i as f64 / (N_MELS + 1) as f64)).collect();
    let bins = N_FFT / 2 + 1;
    (0..N_MELS)
        .map(|band| {
            let (left, centre, right) = (edges[band], edges[band + 1], edges[band + 2]);
            let area = 2.0 / (right - left);
            let weights: Vec<f64> = (0..bins)
                .map(|bin| {
                    let hz = bin as f64 * sample_rate / N_FFT as f64;
                    ((hz - left) / (centre - left)).min((right - hz) / (right - centre)).max(0.0) * area
                })
                .collect();
            let first = weights.iter().position(|&w| w > 0.0).unwrap_or(0);
            let last = weights.iter().rposition(|&w| w > 0.0).map_or(first, |index| index + 1);
            (first, weights[first..last].iter().map(|&w| w as f32).collect())
        })
        .collect()
}

/// Number of spectrogram frames the RMVPE network needs: it downsamples by 32, so the
/// input is zero-padded up to the next multiple and the padding is cut from the output.
pub fn padded_frames(frames: usize) -> usize {
    frames.div_ceil(32) * 32
}

/// Turns the network's salience (`[frames][360]`, row-major) into Hz.
///
/// Each frame takes the salience-weighted mean of the bin centres within four bins of
/// the strongest one. Frames whose peak is below `threshold` are unvoiced.
pub fn decode_salience(salience: &[f32], threshold: f32) -> Vec<f32> {
    salience
        .chunks_exact(SALIENCE_BINS)
        .map(|frame| {
            let (centre, peak) = frame.iter().enumerate().fold((0, f32::MIN), |best, (bin, &value)| if value > best.1 { (bin, value) } else { best });
            if peak < threshold {
                return 0.0;
            }
            let range = centre.saturating_sub(4)..(centre + 5).min(SALIENCE_BINS);
            let (mut weighted, mut total) = (0.0f64, 0.0f64);
            for bin in range {
                weighted += frame[bin] as f64 * (CENTS_PER_BIN * bin as f64 + CENTS_OFFSET);
                total += frame[bin] as f64;
            }
            let cents = weighted / total;
            (10.0 * 2f64.powf(cents / 1200.0)) as f32
        })
        .collect()
}

/// What the synthesizer takes for pitch.
#[derive(Debug, Clone, PartialEq)]
pub struct Pitch {
    /// Mel-quantised pitch, 1..=255.
    pub coarse: Vec<i64>,
    /// Continuous pitch in Hz after interpolation and key change.
    pub continuous: Vec<f32>,
}

const F0_MIN: f64 = 50.0;
const F0_MAX: f64 = 1100.0;

fn hz_to_mel(hz: f64) -> f64 {
    1127.0 * (1.0 + hz / 700.0).ln()
}

/// Fills unvoiced frames by linear interpolation between the voiced frames around them;
/// leading and trailing unvoiced runs take the nearest voiced value. A track without any
/// voiced frame is left at zero.
pub fn interpolate_unvoiced(f0: &mut [f32]) {
    let voiced: Vec<usize> = (0..f0.len()).filter(|&index| f0[index] > 0.0).collect();
    let (Some(&first), Some(&last)) = (voiced.first(), voiced.last()) else { return };
    let head = f0[first];
    f0[..first].fill(head);
    let tail = f0[last];
    f0[last + 1..].fill(tail);
    for pair in voiced.windows(2) {
        let (left, right) = (pair[0], pair[1]);
        let (start, end) = (f0[left] as f64, f0[right] as f64);
        for index in left + 1..right {
            let position = (index - left) as f64 / (right - left) as f64;
            f0[index] = (start + (end - start) * position) as f32;
        }
    }
}

/// Interpolates, shifts by `transpose` semitones and quantises an extractor's F0 track.
pub fn prepare_pitch(mut f0: Vec<f32>, transpose: f64) -> Pitch {
    interpolate_unvoiced(&mut f0);
    let shift = 2f64.powf(transpose / 12.0);
    let (mel_min, mel_max) = (hz_to_mel(F0_MIN), hz_to_mel(F0_MAX));
    let mut coarse = Vec::with_capacity(f0.len());
    for value in f0.iter_mut() {
        *value = (*value as f64 * shift) as f32;
        let mut mel = hz_to_mel(*value as f64);
        if mel > 0.0 {
            mel = (mel - mel_min) * 254.0 / (mel_max - mel_min) + 1.0;
        }
        coarse.push(mel.clamp(1.0, 255.0).round_ties_even() as i64);
    }
    Pitch { coarse, continuous: f0 }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unvoiced_frames_are_bridged_and_edges_held() {
        let mut f0 = vec![0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 200.0, 0.0];
        interpolate_unvoiced(&mut f0);
        assert_eq!(f0, vec![100.0, 100.0, 100.0, 125.0, 150.0, 175.0, 200.0, 200.0]);
        let mut silent = vec![0.0; 4];
        interpolate_unvoiced(&mut silent);
        assert_eq!(silent, vec![0.0; 4]);
    }

    #[test]
    fn quantisation_covers_the_range_and_clamps() {
        let pitch = prepare_pitch(vec![50.0, 1100.0, 20.0, 4000.0, 220.0], 0.0);
        assert_eq!(pitch.coarse[0], 1);
        assert_eq!(pitch.coarse[1], 255);
        assert_eq!(pitch.coarse[2], 1);
        assert_eq!(pitch.coarse[3], 255);
        // 220 Hz: (308.0 - 77.75) * 254 / (1064.4 - 77.75) + 1 = 60.27
        assert_eq!(pitch.coarse[4], 60);
        assert_eq!(prepare_pitch(vec![0.0; 3], 5.0).coarse, vec![1, 1, 1]);
    }

    #[test]
    fn transpose_shifts_by_semitones() {
        let pitch = prepare_pitch(vec![220.0], 12.0);
        assert!((pitch.continuous[0] - 440.0).abs() < 1e-3);
    }

    #[test]
    fn salience_decodes_to_the_bin_frequency() {
        let mut salience = vec![0.0f32; 2 * SALIENCE_BINS];
        salience[100] = 0.9;
        salience[SALIENCE_BINS + 5] = 0.01; // below the voicing threshold
        let f0 = decode_salience(&salience, 0.03);
        let expected = 10.0 * 2f64.powf((20.0 * 100.0 + CENTS_OFFSET) / 1200.0);
        assert!((f0[0] as f64 - expected).abs() < 1e-3);
        assert_eq!(f0[1], 0.0);
    }

    #[test]
    fn mel_spectrogram_has_one_frame_per_hop_plus_one() {
        let audio: Vec<f32> = (0..1600).map(|n| (n as f32 * 0.1).sin()).collect();
        let (mel, frames) = MelSpectrogram::new().compute(&audio);
        assert_eq!(frames, 11);
        assert_eq!(mel.len(), 128 * 11);
        assert!(mel.iter().all(|value| value.is_finite()));
    }
}
