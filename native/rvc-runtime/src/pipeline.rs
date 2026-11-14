//! Offline conversion: the whole pipeline of specification section 2, from 16 kHz input
//! to the waveform at the model's sample rate.

use crate::audio;
use crate::backend::{FeatureExtractor, Synthesizer, MIN_FEATURE_SAMPLES};
use crate::error::{Error, Result};
use crate::f0::{self, F0Estimator, Pitch, HOP};
use crate::filter;
use crate::index::FeatureIndex;
use crate::model::Version;
use crate::noise::{Generator, NoiseMode};

/// Sample rate of everything before the synthesizer.
pub const INPUT_RATE: u32 = 16_000;

/// How long input is cut into pieces (specification section 4). All values in seconds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Chunking {
    /// Context added before and after every piece and cut from its output.
    pub pad: usize,
    /// How far either side of a nominal cut the quietest point is searched for.
    pub query: usize,
    /// Nominal distance between cuts.
    pub center: usize,
    /// Inputs up to this length are converted in one piece.
    pub max: usize,
}

impl Default for Chunking {
    /// The reference values for a capable GPU. Memory grows with the square of the piece
    /// length (self-attention over 100 frames per second); lower `center` and `max` on
    /// small machines.
    fn default() -> Self {
        Chunking { pad: 3, query: 10, center: 60, max: 65 }
    }
}

/// The conversion parameters of specification section 11.
#[derive(Debug, Clone, PartialEq)]
pub struct Options {
    /// Key change in semitones.
    pub transpose: i32,
    /// Share of the retrieved features in the blend, 0..=1. Ignored without an index.
    pub index_rate: f32,
    /// How much of the converted features unvoiced frames keep, 0..=0.5 (0.5 disables).
    pub protect: f32,
    pub speaker: usize,
    /// 1 keeps the synthesizer's loudness, lower values follow the input's.
    pub rms_mix_rate: f32,
    /// Output sample rate; 0 keeps the model's.
    pub resample_sr: u32,
    pub noise: NoiseMode,
    pub chunking: Chunking,
}

impl Default for Options {
    fn default() -> Self {
        Options { transpose: 0, index_rate: 0.75, protect: 0.33, speaker: 0, rms_mix_rate: 1.0, resample_sr: 0, noise: NoiseMode::Random, chunking: Chunking::default() }
    }
}

/// The converted audio. Samples are float; multiply by `int16_gain` for 16-bit output
/// (it already contains the peak limiting of specification section 10).
#[derive(Debug, Clone)]
pub struct Converted {
    pub samples: Vec<f32>,
    pub sample_rate: u32,
    pub int16_gain: f32,
}

/// Intermediate values of one piece, for verification.
#[derive(Debug, Clone, Default)]
pub struct SegmentTrace {
    /// Content features at 50 fps, before blending.
    pub features: Vec<f32>,
    /// What the synthesizer received at 100 fps (after blending, doubling and protect).
    pub synthesizer_features: Vec<f32>,
    pub coarse: Vec<i64>,
    pub continuous: Vec<f32>,
    /// Synthesizer output including the padding that is cut afterwards.
    pub audio: Vec<f32>,
}

/// Intermediate values of a conversion, for verification. Holds audio-derived data and is
/// never logged.
#[derive(Debug, Clone, Default)]
pub struct Trace {
    /// High-passed and padded input, as handed to the pitch extractor.
    pub padded: Vec<f64>,
    /// Extractor output in Hz, 0 where unvoiced.
    pub f0: Vec<f32>,
    pub pitch: Option<Pitch>,
    /// Cut positions in input samples.
    pub cuts: Vec<usize>,
    pub segments: Vec<SegmentTrace>,
}

/// Everything needed to convert with one voice model.
pub struct Converter {
    pub features: FeatureExtractor,
    pub pitch: Box<dyn F0Estimator>,
    pub synthesizer: Synthesizer,
    pub index: Option<FeatureIndex>,
    pub version: Version,
}

/// Mirrors the signal about its ends without repeating the end samples.
fn reflect_pad(signal: &[f64], pad: usize) -> Vec<f64> {
    let last = signal.len() as isize - 1;
    let at = |index: isize| -> f64 {
        if last <= 0 {
            return signal.first().copied().unwrap_or(0.0);
        }
        let period = 2 * last;
        let folded = index.rem_euclid(period);
        signal[if folded > last { period - folded } else { folded } as usize]
    };
    (-(pad as isize)..signal.len() as isize + pad as isize).map(at).collect()
}

/// Where to cut a long input: near every multiple of `center`, at the start of the
/// quietest 10 ms within `query` either side.
fn cut_points(signal: &[f64], chunking: &Chunking) -> Vec<usize> {
    let rate = INPUT_RATE as usize;
    let (query, center, max) = (chunking.query * rate, chunking.center * rate, chunking.max * rate);
    if signal.len() <= max || center == 0 {
        return Vec::new();
    }
    let padded = reflect_pad(signal, HOP / 2);
    // Sum of magnitudes over the 10 ms window starting at each sample (running sum).
    let mut level = Vec::with_capacity(signal.len());
    let mut sum: f64 = padded[..HOP].iter().map(|x| x.abs()).sum();
    for index in 0..signal.len() {
        level.push(sum);
        sum += padded[index + HOP].abs() - padded[index].abs();
    }
    (center..signal.len())
        .step_by(center)
        .map(|nominal| {
            let start = nominal.saturating_sub(query);
            let end = (nominal + query).min(signal.len());
            let quietest = level[start..end].iter().enumerate().fold((0, f64::INFINITY), |best, (offset, &value)| if value < best.1 { (offset, value) } else { best }).0;
            (start + quietest) / HOP * HOP
        })
        .collect()
}

impl Converter {
    /// Sample rate of the synthesizer output before any resampling.
    pub fn model_rate(&self) -> u32 {
        self.synthesizer.sample_rate()
    }

    /// Converts mono 16 kHz audio.
    pub fn convert(&mut self, audio: &[f32], options: &Options) -> Result<Converted> {
        self.convert_traced(audio, options, None)
    }

    /// As [`Converter::convert`], also recording the intermediate values.
    pub fn convert_traced(&mut self, audio: &[f32], options: &Options, mut trace: Option<&mut Trace>) -> Result<Converted> {
        if !(0.0..=1.0).contains(&options.index_rate) || !(0.0..=0.5).contains(&options.protect) || !(0.0..=1.0).contains(&options.rms_mix_rate) {
            return Err(Error::invalid("index_rate and rms_mix_rate must be within 0..=1 and protect within 0..=0.5"));
        }
        if audio.len() < MIN_FEATURE_SAMPLES {
            return Err(Error::invalid("input is too short to convert"));
        }
        if audio.iter().any(|sample| !sample.is_finite()) {
            return Err(Error::invalid("input contains non-finite samples"));
        }
        let rate = INPUT_RATE as usize;
        let model_rate = self.model_rate();
        let per_frame = self.synthesizer.samples_per_frame();
        let signal: Vec<f64> = audio.iter().map(|&x| x as f64).collect();
        let filtered = filter::filtfilt(&filter::input_highpass(), &signal);
        let cuts = cut_points(&filtered, &options.chunking);
        let pad = options.chunking.pad * rate;
        let padded = reflect_pad(&filtered, pad);
        let padded_f32: Vec<f32> = padded.iter().map(|&x| x as f32).collect();

        let pitch = if self.synthesizer.uses_pitch() {
            let track = self.pitch.estimate(&padded_f32)?;
            if let Some(trace) = trace.as_deref_mut() {
                trace.f0 = track.clone();
            }
            Some(f0::prepare_pitch(track, options.transpose as f64))
        } else {
            None
        };
        if let Some(trace) = trace.as_deref_mut() {
            trace.padded = padded.clone();
            trace.pitch = pitch.clone();
            trace.cuts = cuts.clone();
        }

        // One generator for the whole conversion, so a seed fixes every piece.
        let mut generator = Generator::new(options.noise);
        let trim = options.chunking.pad * per_frame * f0::FRAME_RATE;
        let mut output = Vec::with_capacity(audio.len() / HOP * per_frame);
        let mut start = 0;
        for end in cuts.iter().map(|&cut| Some(cut)).chain([None]) {
            // A piece runs from its cut to the next one, plus the padding on both sides.
            let stop = end.map_or(padded.len(), |cut| (cut + 2 * pad + HOP).min(padded.len()));
            let frames = start / HOP..end.map_or(usize::MAX, |cut| (cut + 2 * pad) / HOP);
            let mut segment = SegmentTrace::default();
            let piece = self.convert_piece(&padded_f32[start..stop], pitch.as_ref(), frames, options, &mut generator, trace.is_some().then_some(&mut segment))?;
            if piece.len() > 2 * trim {
                output.extend_from_slice(&piece[trim..piece.len() - trim]);
            }
            if let Some(trace) = trace.as_deref_mut() {
                trace.segments.push(segment);
            }
            if let Some(cut) = end {
                start = cut;
            }
        }

        if options.rms_mix_rate != 1.0 {
            audio::rms_mix(&filtered, INPUT_RATE, &mut output, model_rate, options.rms_mix_rate);
        }
        let mut sample_rate = model_rate;
        if options.resample_sr >= INPUT_RATE && options.resample_sr != model_rate {
            output = audio::resample(&output, model_rate, options.resample_sr);
            sample_rate = options.resample_sr;
        }
        let int16_gain = audio::peak_gain(&output);
        Ok(Converted { samples: output, sample_rate, int16_gain })
    }

    fn convert_piece(
        &mut self,
        audio: &[f32],
        pitch: Option<&Pitch>,
        frames: std::ops::Range<usize>,
        options: &Options,
        generator: &mut Generator,
        mut trace: Option<&mut SegmentTrace>,
    ) -> Result<Vec<f32>> {
        let dim = self.version.feature_dim();
        let mut features = self.features.extract(audio, self.version)?;
        if let Some(trace) = trace.as_deref_mut() {
            trace.features = features.clone();
        }
        let protect = pitch.is_some() && options.protect < 0.5;
        let original = protect.then(|| features.clone());
        if let (Some(index), true) = (&self.index, options.index_rate != 0.0) {
            if index.dim() != dim {
                return Err(Error::invalid("the index was built for a different model version"));
            }
            index.blend(&mut features, options.index_rate)?;
        }

        // 50 fps to 100 fps by repeating every frame, then no longer than the audio allows.
        let count = (features.len() / dim * 2).min(audio.len() / HOP);
        let double = |source: &[f32]| -> Vec<f32> { (0..count).flat_map(|frame| source[frame / 2 * dim..(frame / 2 + 1) * dim].iter().copied()).collect() };
        let mut features = double(&features);

        let tracks = match pitch {
            Some(pitch) => {
                let first = frames.start.min(pitch.coarse.len());
                let last = frames.end.min(pitch.coarse.len()).min(first + count);
                if last - first < count {
                    return Err(Error::invalid("pitch track is shorter than the features"));
                }
                Some((&pitch.coarse[first..last], &pitch.continuous[first..last]))
            }
            None => None,
        };
        if let (Some(original), Some((_, continuous))) = (original, tracks) {
            let original = double(&original);
            for (frame, &hz) in continuous.iter().enumerate() {
                // Frames without pitch keep only `protect` of the converted features.
                let keep = if hz < 1.0 { options.protect } else { 1.0 };
                if keep != 1.0 {
                    for (value, source) in features[frame * dim..(frame + 1) * dim].iter_mut().zip(&original[frame * dim..(frame + 1) * dim]) {
                        *value = *value * keep + source * (1.0 - keep);
                    }
                }
            }
        }
        let audio = self.synthesizer.synthesize(&features, tracks, options.speaker, generator)?;
        if let Some(trace) = trace {
            if let Some((coarse, continuous)) = tracks {
                trace.coarse = coarse.to_vec();
                trace.continuous = continuous.to_vec();
            }
            trace.synthesizer_features = features;
            trace.audio = audio.clone();
        }
        Ok(audio)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reflect_padding_mirrors_without_repeating_the_ends() {
        assert_eq!(reflect_pad(&[1.0, 2.0, 3.0, 4.0], 2), vec![3.0, 2.0, 1.0, 2.0, 3.0, 4.0, 3.0, 2.0]);
        // Longer than the signal: keeps folding back and forth.
        assert_eq!(reflect_pad(&[1.0, 2.0, 3.0], 4), vec![1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0]);
    }

    #[test]
    fn short_input_is_not_cut() {
        let signal = vec![0.1; 16_000 * 5];
        assert!(cut_points(&signal, &Chunking::default()).is_empty());
    }

    #[test]
    fn long_input_is_cut_at_the_quietest_point_near_each_interval() {
        let chunking = Chunking { pad: 1, query: 1, center: 2, max: 3 };
        let mut signal = vec![0.5; 16_000 * 5];
        // A silent stretch a little after the first nominal cut at 2 s.
        signal[35_000..36_000].fill(0.0);
        let cuts = cut_points(&signal, &chunking);
        assert_eq!(cuts.len(), 2);
        assert!((35_000..36_000).contains(&cuts[0]), "{cuts:?}");
        assert_eq!(cuts[0] % HOP, 0);
    }
}
