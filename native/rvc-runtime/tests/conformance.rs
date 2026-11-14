//! Conformance against the reference implementation (specification section 13).
//!
//! Every test compares against values recorded by `reference/dump_reference.py`. Without
//! those fixtures the tests report themselves as skipped; `RVC_REQUIRE_REFERENCE=1` turns
//! a missing fixture into a failure. Measured values are printed (`--nocapture`) as lines
//! starting with `METRIC`; they are numbers only, never audio or text.
mod common;

use std::path::Path;
use std::sync::{Mutex, MutexGuard};

use common::{case, case_json, cosine, max_abs_error, npy, relative_error};
use rvc_runtime::f0::{prepare_pitch, F0Estimator};
use rvc_runtime::noise::Generator;
use rvc_runtime::{audio, Chunking, Converter, Device, FeatureExtractor, FeatureIndex, NoiseMode, Options, Rmvpe, Synthesizer, Trace, Version, VoiceModel};

/// The networks are large; run one test at a time.
fn serial() -> MutexGuard<'static, ()> {
    static LOCK: Mutex<()> = Mutex::new(());
    LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// An exported network under the reference directory, or `None` (with a notice) when the
/// reference environment has not been prepared.
fn asset(relative: &str) -> Option<std::path::PathBuf> {
    let path = common::reference_dir().join(relative);
    if path.is_file() {
        return Some(path);
    }
    if std::env::var_os("RVC_REQUIRE_REFERENCE").is_some() {
        panic!("reference asset `{relative}` is missing; see native/rvc-runtime/README.md");
    }
    eprintln!("SKIPPED: reference asset `{relative}` is missing (see native/rvc-runtime/README.md)");
    None
}

fn hubert() -> Option<FeatureExtractor> {
    Some(FeatureExtractor::load(&asset("assets/hubert_base/hubert.onnx")?, Device::Cpu).unwrap())
}

fn rmvpe() -> Option<Rmvpe> {
    Some(Rmvpe::load(&asset("assets/rmvpe/rmvpe.onnx")?, Device::Cpu).unwrap())
}

struct Case {
    folder: std::path::PathBuf,
    json: serde_json::Value,
}

impl Case {
    fn open(name: &str) -> Option<Self> {
        let folder = case(name)?;
        let json = case_json(&folder);
        Some(Case { folder, json })
    }

    fn array(&self, name: &str) -> common::Npy {
        npy(&self.folder.join(format!("{name}.npy")))
    }

    fn model(&self) -> VoiceModel {
        VoiceModel::load(Path::new(self.json["model"].as_str().unwrap())).unwrap()
    }

    fn options(&self) -> Options {
        let number = |key: &str| self.json[key].as_f64().unwrap();
        let chunk: Vec<usize> = self.json["chunk"].as_array().unwrap().iter().map(|value| value.as_u64().unwrap() as usize).collect();
        Options {
            transpose: number("transpose") as i32,
            index_rate: number("index_rate") as f32,
            protect: number("protect") as f32,
            speaker: number("sid") as usize,
            rms_mix_rate: number("rms_mix_rate") as f32,
            resample_sr: number("resample_sr") as u32,
            noise: match self.json["noise"].as_str().unwrap() {
                "zero" => NoiseMode::Zero,
                _ => NoiseMode::Seeded(number("seed") as u64),
            },
            chunking: Chunking { pad: chunk[0], query: chunk[1], center: chunk[2], max: chunk[3] },
        }
    }

    fn converter(&self) -> Converter {
        let model = self.model();
        let index = self.json["index"].as_str().map(|path| FeatureIndex::load(Path::new(path)).unwrap());
        Converter {
            features: hubert().expect("the fixtures exist, so the networks must"),
            pitch: Box::new(rmvpe().expect("the fixtures exist, so the networks must")),
            synthesizer: Synthesizer::new(&model, Device::Cpu).unwrap(),
            index,
            version: model.version,
        }
    }
}

fn snr_db(found: &[f32], expected: &[f32]) -> f64 {
    -20.0 * relative_error(found, expected).log10()
}

const ZERO_NOISE_CASES: [&str; 8] = [
    "saisho_48k_zero",
    "saisho_48k_noindex_zero",
    "pretrained_40k_zero",
    "random_v2_f0_40k_zero",
    "random_v2_f0_32k_zero",
    "random_v2_nof0_48k_zero",
    "random_v1_f0_40k_zero",
    "random_v1_nof0_32k_zero",
];

#[test]
fn input_filter_and_padding_match() {
    let _guard = serial();
    let Some(case) = Case::open("saisho_48k_zero") else { return };
    let input = case.array("input_16k").f32();
    let expected = case.array("f0_input").f64();
    let signal: Vec<f64> = input.iter().map(|&x| x as f64).collect();
    let filtered = rvc_runtime::filter::filtfilt(&rvc_runtime::filter::input_highpass(), &signal);
    let pad = (expected.len() - filtered.len()) / 2;
    let worst = filtered.iter().zip(&expected[pad..]).map(|(a, b)| (a - b).abs()).fold(0.0, f64::max);
    eprintln!("METRIC filter: max abs error {worst:.3e} over {} samples", filtered.len());
    assert!(worst < 1e-6);
}

#[test]
fn hubert_features_match() {
    let _guard = serial();
    let Some(mut extractor) = hubert() else { return };
    for (name, version) in [("saisho_48k_zero", Version::V2), ("random_v1_f0_40k_zero", Version::V1)] {
        let Some(case) = Case::open(name) else { continue };
        let found = extractor.extract(&case.array("hubert_input_0").f32(), version).unwrap();
        let expected = case.array("hubert_0").f32();
        let (mean, lowest) = cosine(&found, &expected, version.feature_dim());
        let error = relative_error(&found, &expected);
        eprintln!("METRIC hubert {version:?}: relative error {error:.3e}, cosine mean {mean:.7} min {lowest:.7}, {} frames", expected.len() / version.feature_dim());
        assert!(error < 2e-3, "relative error {error}");
        assert!(lowest > 0.9999, "cosine {lowest}");
    }
}

/// Voiced/unvoiced agreement and the cents error where both are voiced.
fn f0_agreement(found: &[f32], expected: &[f32]) -> (f64, f64, f64) {
    assert_eq!(found.len(), expected.len());
    let agree = found.iter().zip(expected).filter(|(a, b)| (**a > 0.0) == (**b > 0.0)).count();
    let cents: Vec<f64> = found.iter().zip(expected).filter(|(a, b)| **a > 0.0 && **b > 0.0).map(|(a, b)| (1200.0 * (*a as f64 / *b as f64).log2()).abs()).collect();
    let mean = cents.iter().sum::<f64>() / cents.len().max(1) as f64;
    (agree as f64 / found.len() as f64, mean, cents.iter().copied().fold(0.0, f64::max))
}

#[test]
fn rmvpe_f0_and_quantised_pitch_match() {
    let _guard = serial();
    let Some(mut estimator) = rmvpe() else { return };
    for name in ["saisho_48k_zero", "saisho_48k_noindex_zero", "saisho_48k_long_zero"] {
        let Some(case) = Case::open(name) else { continue };
        let input: Vec<f32> = case.array("f0_input").f64().into_iter().map(|x| x as f32).collect();
        let expected = case.array("f0_raw").f32();
        let found = estimator.estimate(&input).unwrap();
        let (agreement, mean, worst) = f0_agreement(&found, &expected);
        eprintln!("METRIC f0 {name}: voicing agreement {:.4}%, cents error mean {mean:.4} max {worst:.4}, {} frames", agreement * 100.0, expected.len());
        assert!(agreement >= 0.995, "voicing agreement {agreement}");
        assert!(mean < 0.5 && worst < 5.0, "cents error mean {mean} max {worst}");

        // Quantisation on the reference's own F0: must be exact.
        let transpose = case.json["transpose"].as_f64().unwrap();
        let (coarse, continuous) = (case.array("coarse").i64(), case.array("pitchf").f32());
        let exact = prepare_pitch(expected.clone(), transpose);
        assert_eq!(exact.coarse, coarse, "quantised pitch from the reference F0");
        assert!(max_abs_error(&exact.continuous, &continuous) < 1e-3);
        // And end to end from our own F0: report how many frames differ.
        let ours = prepare_pitch(found, transpose);
        let differing = ours.coarse.iter().zip(&coarse).filter(|(a, b)| a != b).count();
        let rate = differing as f64 / coarse.len() as f64;
        let off_by_more = ours.coarse.iter().zip(&coarse).filter(|(a, b)| (**a - **b).abs() > 1).count();
        eprintln!("METRIC coarse {name}: {differing} of {} frames differ ({:.3}%), {off_by_more} by more than one step", coarse.len(), rate * 100.0);
        assert!(rate < 0.02, "coarse mismatch rate {rate}");
        assert_eq!(off_by_more, 0);
    }
}

#[test]
fn index_neighbours_and_blend_match() {
    let _guard = serial();
    let Some(case) = Case::open("saisho_48k_zero") else { return };
    let index = FeatureIndex::load(Path::new(case.json["index"].as_str().unwrap())).unwrap();
    let queries = case.array("search_queries_0").f32();
    let (ids, scores) = (case.array("search_ids_0").i64(), case.array("search_scores_0").f32());
    let k = rvc_runtime::index::NEIGHBOURS;
    let (mut same_sets, mut same_order, mut worst) = (0, 0, 0.0f32);
    let frames = queries.len() / index.dim();
    for frame in 0..frames {
        let found = index.search(&queries[frame * index.dim()..(frame + 1) * index.dim()], k);
        let found_ids: Vec<i64> = found.iter().map(|neighbour| neighbour.id).collect();
        let expected = &ids[frame * k..(frame + 1) * k];
        same_order += (found_ids == expected) as usize;
        let (mut a, mut b) = (found_ids.clone(), expected.to_vec());
        a.sort_unstable();
        b.sort_unstable();
        same_sets += (a == b) as usize;
        for (neighbour, score) in found.iter().zip(&scores[frame * k..(frame + 1) * k]) {
            worst = worst.max((neighbour.distance - score).abs() / score);
        }
    }
    eprintln!("METRIC index: {} vectors, neighbour sets equal in {same_sets}/{frames} frames (same order in {same_order}), distance relative error max {worst:.3e}", index.len());
    assert_eq!(same_sets, frames);
    assert!(worst < 1e-4);

    // Blend the reference's features and compare with what its synthesizer received
    // (blended, doubled; protect leaves every frame alone here because the interpolated
    // pitch is never zero).
    let mut blended = queries.clone();
    index.blend(&mut blended, case.json["index_rate"].as_f64().unwrap() as f32).unwrap();
    let expected = case.array("synth_feats_0").f32();
    let dim = index.dim();
    let doubled: Vec<f32> = (0..expected.len() / dim).flat_map(|frame| blended[frame / 2 * dim..(frame / 2 + 1) * dim].iter().copied()).collect();
    let error = relative_error(&doubled, &expected);
    eprintln!("METRIC blend: relative error {error:.3e}, cosine min {:.7}", cosine(&doubled, &expected, dim).1);
    assert!(error < 1e-4, "blend relative error {error}");
}

#[test]
fn synthesizer_matches_for_every_model_variant() {
    let _guard = serial();
    for name in ZERO_NOISE_CASES {
        let Some(case) = Case::open(name) else { continue };
        let model = case.model();
        let mut synthesizer = Synthesizer::new(&model, Device::Cpu).unwrap();
        let features = case.array("synth_feats_0").f32();
        let tracks = model.f0.then(|| (case.array("synth_pitch_0").i64(), case.array("synth_pitchf_0").f32()));
        let expected = case.array("synth_audio_0").f32();
        let mut generator = Generator::new(NoiseMode::Zero);
        let started = std::time::Instant::now();
        let found = synthesizer.synthesize(&features, tracks.as_ref().map(|(coarse, continuous)| (&coarse[..], &continuous[..])), case.options().speaker, &mut generator).unwrap();
        let seconds = found.len() as f64 / model.config.sample_rate as f64;
        eprintln!(
            "METRIC synth {name} ({:?}, f0 {}, {} Hz): SNR {:.1} dB, max abs error {:.2e}, {:.2} s audio in {:.2} s",
            model.version,
            model.f0,
            model.config.sample_rate,
            snr_db(&found, &expected),
            max_abs_error(&found, &expected),
            seconds,
            started.elapsed().as_secs_f64()
        );
        assert!(snr_db(&found, &expected) > 70.0, "{name}");
    }
}

/// Runs a case end to end and returns our output in the reference's 16-bit scale.
fn run(case: &Case, trace: Option<&mut Trace>) -> (Vec<f32>, Vec<f32>, u32) {
    let mut converter = case.converter();
    let input = case.array("input_16k").f32();
    let converted = converter.convert_traced(&input, &case.options(), trace).unwrap();
    let ours: Vec<f32> = converted.samples.iter().map(|&x| (x * converted.int16_gain).clamp(-32768.0, 32767.0).trunc()).collect();
    (ours, case.array("output").f32(), converted.sample_rate)
}

#[test]
fn whole_pipeline_matches_without_noise() {
    let _guard = serial();
    for name in ZERO_NOISE_CASES {
        let Some(case) = Case::open(name) else { continue };
        let mut trace = Trace::default();
        let (ours, expected, _) = run(&case, Some(&mut trace));
        assert_eq!(ours.len(), expected.len(), "{name}: output length");
        let segment = &trace.segments[0];
        let features = relative_error(&segment.synthesizer_features, &case.array("synth_feats_0").f32());
        let scale = |signal: &[f32]| signal.iter().map(|x| x / 32768.0).collect::<Vec<f32>>();
        let distance = log_spectral_distance(&scale(&ours), &scale(&expected));
        eprintln!("METRIC pipeline {name}: synthesizer input features relative error {features:.3e}, output SNR {:.1} dB, log-spectral distance {distance:.3} dB", snr_db(&ours, &expected));
        assert!(features < 1e-4, "{name}: features {features}");
        let model = case.model();
        if model.f0 {
            // A trained source filter turns a pitch difference of a hundredth of a cent into a
            // slowly growing phase offset, so samples drift apart although the sound does not.
            // With the reference's pitch and our own features the samples agree again.
            let tracks = (case.array("synth_pitch_0").i64(), case.array("synth_pitchf_0").f32());
            let mut synthesizer = Synthesizer::new(&model, Device::Cpu).unwrap();
            let found = synthesizer.synthesize(&segment.synthesizer_features, Some((&tracks.0, &tracks.1)), case.options().speaker, &mut Generator::new(NoiseMode::Zero)).unwrap();
            let snr = snr_db(&found, &case.array("synth_audio_0").f32());
            // How much such a pitch difference costs: the reference's inputs with its pitch
            // raised by 0.02 cents, against its own output.
            let shifted: Vec<f32> = tracks.1.iter().map(|hz| hz * 2f32.powf(0.02 / 1200.0)).collect();
            let reference_features = case.array("synth_feats_0").f32();
            let nudged = synthesizer.synthesize(&reference_features, Some((&tracks.0, &shifted)), case.options().speaker, &mut Generator::new(NoiseMode::Zero)).unwrap();
            let nudged = snr_db(&nudged, &case.array("synth_audio_0").f32());
            eprintln!("METRIC pipeline {name}: with the reference pitch track, SNR {snr:.1} dB; reference inputs with pitch +0.02 cents, SNR {nudged:.1} dB");
            assert!(snr > 70.0, "{name}: SNR {snr}");
        } else {
            assert!(snr_db(&ours, &expected) > 60.0, "{name}");
        }
    }
}

#[test]
fn long_input_is_cut_like_the_reference() {
    let _guard = serial();
    let Some(case) = Case::open("saisho_48k_long_zero") else { return };
    let mut trace = Trace::default();
    let (ours, expected, _) = run(&case, Some(&mut trace));
    let segments = case.json["segments"].as_u64().unwrap() as usize;
    let scale = |signal: &[f32]| signal.iter().map(|x| x / 32768.0).collect::<Vec<f32>>();
    let distance = log_spectral_distance(&scale(&ours), &scale(&expected));
    eprintln!("METRIC long: {} pieces (reference {segments}), cut at sample {:?}, log-spectral distance {distance:.3} dB over {} samples", trace.segments.len(), trace.cuts, ours.len());
    assert!(segments > 1, "the fixture should exercise cutting");
    assert_eq!(trace.segments.len(), segments);
    assert_eq!(ours.len(), expected.len());
    for (number, segment) in trace.segments.iter().enumerate() {
        let reference = case.array(&format!("synth_audio_{number}")).f32();
        assert_eq!(segment.audio.len(), reference.len(), "piece {number} length");
    }
}

#[test]
fn loudness_mix_and_resampling_match() {
    let _guard = serial();
    let Some(case) = Case::open("saisho_48k_post") else { return };
    let options = case.options();
    let model_rate = case.json["sample_rate"].as_u64().unwrap() as u32;
    // Post-process the reference's own synthesizer output and compare with its final output.
    let synthesized = case.array("synth_audio_0").f32();
    let trim = options.chunking.pad * model_rate as usize;
    let mut output = synthesized[trim..synthesized.len() - trim].to_vec();
    let signal: Vec<f64> = case.array("input_16k").f32().iter().map(|&x| x as f64).collect();
    let filtered = rvc_runtime::filter::filtfilt(&rvc_runtime::filter::input_highpass(), &signal);
    audio::rms_mix(&filtered, 16_000, &mut output, model_rate, options.rms_mix_rate);
    let expected = case.array("output").f32();
    let resampled = audio::resample(&output, model_rate, options.resample_sr);
    let gain = audio::peak_gain(&resampled);
    let ours: Vec<f32> = resampled.iter().map(|x| (x * gain).trunc()).collect();
    assert_eq!(ours.len(), expected.len());
    let snr = snr_db(&ours, &expected);
    eprintln!("METRIC post: loudness mix {} and resampling {model_rate} -> {} Hz on the reference synthesizer output: SNR {snr:.1} dB", options.rms_mix_rate, options.resample_sr);
    assert!(snr > 35.0, "SNR {snr}");

    let (ours, expected, rate) = run(&case, None);
    assert_eq!((rate, ours.len()), (44_100, expected.len()));
    let scale = |signal: &[f32]| signal.iter().map(|x| x / 32768.0).collect::<Vec<f32>>();
    let distance = log_spectral_distance(&scale(&ours), &scale(&expected));
    eprintln!("METRIC post: end to end log-spectral distance {distance:.3} dB");
}

/// Mean log-spectral distance in dB between two signals (1024-point frames, hop 256),
/// over frames where the reference is not silent.
fn log_spectral_distance(found: &[f32], expected: &[f32]) -> f64 {
    use rustfft::num_complex::Complex32;
    let fft = rustfft::FftPlanner::<f32>::new().plan_fft_forward(1024);
    let spectrum = |signal: &[f32]| -> Vec<f64> {
        let mut buffer: Vec<Complex32> = signal.iter().enumerate().map(|(n, &x)| Complex32::new(x * (0.5 - 0.5 * (2.0 * std::f32::consts::PI * n as f32 / 1024.0).cos()), 0.0)).collect();
        fft.process(&mut buffer);
        buffer[..513].iter().map(|bin| (bin.norm_sqr() as f64).max(1e-10).log10() * 10.0).collect()
    };
    let (mut total, mut frames) = (0.0, 0);
    for start in (0..found.len().min(expected.len()).saturating_sub(1024)).step_by(256) {
        let reference = &expected[start..start + 1024];
        if reference.iter().map(|x| x * x).sum::<f32>() / 1024.0 < 1e-6 {
            continue;
        }
        let (a, b) = (spectrum(&found[start..start + 1024]), spectrum(reference));
        total += (a.iter().zip(&b).map(|(x, y)| (x - y).powi(2)).sum::<f64>() / 513.0).sqrt();
        frames += 1;
    }
    total / frames.max(1) as f64
}

#[test]
fn seeded_noise_is_reproducible_and_close_to_the_reference() {
    let _guard = serial();
    let Some(mut estimator) = rmvpe() else { return };
    for name in ["saisho_48k_seeded", "pretrained_40k_seeded"] {
        let Some(case) = Case::open(name) else { continue };
        let (first, expected, rate) = run(&case, None);
        let (second, _, _) = run(&case, None);
        assert_eq!(first, second, "{name}: the same seed must give the same samples");
        let mut other_seed = case.options();
        other_seed.noise = NoiseMode::Seeded(8);
        let different = case.converter().convert(&case.array("input_16k").f32(), &other_seed).unwrap();
        assert!(different.samples.iter().zip(&first).any(|(a, b)| (a * different.int16_gain).trunc() != *b), "{name}: another seed must change the output");

        let scale = |signal: &[f32]| signal.iter().map(|x| x / 32768.0).collect::<Vec<f32>>();
        let (ours, reference) = (scale(&first), scale(&expected));
        // Two different noise draws never match sample by sample. The yardstick is how far
        // apart two draws of the reference itself are (the same case with another seed).
        let Some(other) = Case::open(&format!("{name}_b")) else { continue };
        let other = scale(&other.array("output").f32());
        let (distance, baseline) = (log_spectral_distance(&ours, &reference), log_spectral_distance(&other, &reference));
        let track = |signal: &[f32], estimator: &mut Rmvpe| estimator.estimate(&audio::resample(signal, rate, 16_000)).unwrap();
        let reference_track = track(&reference, &mut estimator);
        let (agreement, mean, _) = f0_agreement(&track(&ours, &mut estimator), &reference_track);
        let (base_agreement, base_mean, _) = f0_agreement(&track(&other, &mut estimator), &reference_track);
        eprintln!("METRIC seeded {name}: log-spectral distance to the reference {distance:.2} dB (reference against itself with another seed: {baseline:.2} dB)");
        eprintln!(
            "METRIC seeded {name}: output F0 voicing agreement {:.2}% and mean cents error {mean:.2} (reference against itself: {:.2}%, {base_mean:.2})",
            agreement * 100.0,
            base_agreement * 100.0
        );
        assert!(distance < baseline * 1.1 + 0.2, "{name}: {distance} dB against a baseline of {baseline} dB");
        assert!(agreement > base_agreement - 0.05 && mean < base_mean * 1.5 + 1.0, "{name}: output pitch");
    }
}
