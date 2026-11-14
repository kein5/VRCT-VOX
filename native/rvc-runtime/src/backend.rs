//! ONNX Runtime sessions for the three networks: content features (HuBERT), pitch
//! salience (RMVPE) and the synthesizer.

use std::path::Path;
use std::sync::OnceLock;

use ort::environment::Environment;
use ort::session::Session;
use ort::value::Tensor;

use crate::error::{Error, Result};
use crate::f0::{self, F0Estimator, MelSpectrogram};
use crate::model::{Version, VoiceModel};
use crate::noise::{self, Generator};
use crate::synth::{self, io};

/// Where the graphs run.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Device {
    #[default]
    Cpu,
    /// CUDA, falling back to the CPU for operators it lacks. Needs the `cuda` feature
    /// and an ONNX Runtime build with the CUDA provider.
    Cuda,
}

fn backend(error: impl std::fmt::Display) -> Error {
    Error::Backend(error.to_string())
}

fn environment() -> Result<&'static Environment> {
    static ENVIRONMENT: OnceLock<std::result::Result<Environment, String>> = OnceLock::new();
    ENVIRONMENT.get_or_init(|| ort::init().with_name("rvc-runtime").build().map_err(|error| error.to_string())).as_ref().map_err(backend)
}

enum Source<'a> {
    File(&'a Path),
    Memory(&'a [u8]),
}

fn session(source: Source, device: Device) -> Result<Session> {
    let mut builder = Session::builder(environment()?).map_err(backend)?;
    if device == Device::Cuda {
        #[cfg(feature = "cuda")]
        {
            builder = builder.with_execution_providers([ort::ep::CUDA::default().build()]).map_err(backend)?;
        }
        #[cfg(not(feature = "cuda"))]
        return Err(Error::invalid("this build has no CUDA support (enable the `cuda` feature)"));
    }
    match source {
        Source::File(path) => builder.commit_from_file(path).map_err(backend),
        Source::Memory(bytes) => builder.commit_from_memory(bytes).map_err(backend),
    }
}

fn first_output(outputs: &ort::session::SessionOutputs, name: &str) -> Result<(Vec<usize>, Vec<f32>)> {
    let value = outputs.get(name).ok_or_else(|| Error::Backend(format!("the graph has no output named {name}")))?;
    let (shape, data) = value.try_extract_tensor::<f32>().map_err(backend)?;
    Ok((shape.iter().map(|&d| d as usize).collect(), data.to_vec()))
}

/// Content features from 16 kHz audio at 50 frames per second.
///
/// The graph is the HuBERT checkpoint exported once by `reference/export_hubert_onnx.py`:
/// input `audio` `[1, samples]`, outputs `features_v2` (last layer, 768 wide) and
/// `features_v1` (ninth layer through the final projection, 256 wide).
pub struct FeatureExtractor {
    session: Session,
}

/// Fewer samples than this give the network no frame at all.
pub const MIN_FEATURE_SAMPLES: usize = 400;

impl FeatureExtractor {
    pub fn load(path: &Path, device: Device) -> Result<Self> {
        let session = session(Source::File(path), device)?;
        for name in ["features_v1", "features_v2"] {
            if !session.outputs().iter().any(|output| output.name() == name) {
                return Err(Error::format("feature extractor", format!("the graph has no `{name}` output")));
            }
        }
        Ok(FeatureExtractor { session })
    }

    /// Row-major `[frames][version.feature_dim()]`. The audio is used as it is; the
    /// checkpoint's preprocessing configuration asks for no normalisation.
    pub fn extract(&mut self, audio: &[f32], version: Version) -> Result<Vec<f32>> {
        if audio.len() < MIN_FEATURE_SAMPLES {
            return Err(Error::invalid("audio is too short for feature extraction"));
        }
        let input = Tensor::from_array(([1, audio.len()], audio.to_vec())).map_err(backend)?;
        let outputs = self.session.run(ort::inputs!["audio" => input]).map_err(backend)?;
        let name = match version {
            Version::V1 => "features_v1",
            Version::V2 => "features_v2",
        };
        let (shape, data) = first_output(&outputs, name)?;
        if shape.last() != Some(&version.feature_dim()) {
            return Err(Error::Backend("feature extractor returned an unexpected width".into()));
        }
        Ok(data)
    }
}

/// RMVPE: log-mel spectrogram in, per-frame salience over 360 pitch bins out.
pub struct Rmvpe {
    session: Session,
    mel: MelSpectrogram,
    input: String,
    output: String,
    /// Peak salience below this marks a frame unvoiced.
    pub threshold: f32,
}

impl Rmvpe {
    pub fn load(path: &Path, device: Device) -> Result<Self> {
        let session = session(Source::File(path), device)?;
        let name = |outlets: &[ort::value::Outlet]| outlets.first().map(|outlet| outlet.name().to_string()).ok_or_else(|| Error::format("pitch extractor", "the graph has no inputs or outputs"));
        let (input, output) = (name(session.inputs())?, name(session.outputs())?);
        Ok(Rmvpe { session, mel: MelSpectrogram::new(), input, output, threshold: 0.03 })
    }
}

impl F0Estimator for Rmvpe {
    fn estimate(&mut self, audio: &[f32]) -> Result<Vec<f32>> {
        let (mel, frames) = self.mel.compute(audio);
        let padded = f0::padded_frames(frames);
        let bands = mel.len() / frames;
        let mut input = vec![0.0f32; bands * padded];
        for band in 0..bands {
            input[band * padded..band * padded + frames].copy_from_slice(&mel[band * frames..(band + 1) * frames]);
        }
        let input = Tensor::from_array(([1, bands, padded], input)).map_err(backend)?;
        let outputs = self.session.run(ort::inputs![self.input.as_str() => input]).map_err(backend)?;
        let (shape, salience) = first_output(&outputs, &self.output)?;
        if shape.last() != Some(&f0::SALIENCE_BINS) || salience.len() < frames * f0::SALIENCE_BINS {
            return Err(Error::Backend("pitch extractor returned an unexpected shape".into()));
        }
        Ok(f0::decode_salience(&salience[..frames * f0::SALIENCE_BINS], self.threshold))
    }
}

/// A voice model ready to synthesize.
pub struct Synthesizer {
    session: Session,
    feature_dim: usize,
    inter_channels: usize,
    samples_per_frame: usize,
    sample_rate: u32,
    speakers: usize,
    f0: bool,
}

impl Synthesizer {
    pub fn new(model: &VoiceModel, device: Device) -> Result<Self> {
        let graph = synth::build_graph(model)?;
        Ok(Synthesizer {
            session: session(Source::Memory(&graph), device)?,
            feature_dim: model.version.feature_dim(),
            inter_channels: model.config.inter_channels,
            samples_per_frame: model.config.samples_per_frame(),
            sample_rate: model.config.sample_rate,
            speakers: model.config.spk_embed_dim,
            f0: model.f0,
        })
    }

    pub fn sample_rate(&self) -> u32 {
        self.sample_rate
    }

    pub fn samples_per_frame(&self) -> usize {
        self.samples_per_frame
    }

    pub fn uses_pitch(&self) -> bool {
        self.f0
    }

    /// Synthesizes `frames * samples_per_frame` samples from 100 fps features
    /// (`[frames][feature_dim]`) and, for pitch-enabled models, the two pitch tracks.
    /// The generator supplies the prior noise first and the excitation noise second.
    pub fn synthesize(&mut self, features: &[f32], pitch: Option<(&[i64], &[f32])>, speaker: usize, generator: &mut Generator) -> Result<Vec<f32>> {
        let frames = features.len() / self.feature_dim;
        if frames == 0 || features.len() != frames * self.feature_dim {
            return Err(Error::invalid("features are empty or not a whole number of frames"));
        }
        if speaker >= self.speakers {
            return Err(Error::invalid(format!("speaker {speaker} does not exist (the model has {})", self.speakers)));
        }
        let noise = generator.normals(frames * self.inter_channels);
        let mut inputs = ort::inputs![
            io::FEATURES => Tensor::from_array(([1, frames, self.feature_dim], features.to_vec())).map_err(backend)?,
            io::NOISE => Tensor::from_array(([1, frames, self.inter_channels], noise)).map_err(backend)?,
            io::SPEAKER => Tensor::from_array(([1usize], vec![speaker as i64])).map_err(backend)?,
        ];
        match (self.f0, pitch) {
            (true, Some((coarse, continuous))) => {
                if coarse.len() != frames || continuous.len() != frames {
                    return Err(Error::invalid("pitch tracks do not match the number of feature frames"));
                }
                if coarse.iter().any(|value| !(0..256).contains(value)) {
                    return Err(Error::invalid("quantised pitch out of range"));
                }
                let excitation = noise::excitation(continuous, self.samples_per_frame, self.sample_rate, generator);
                inputs.push((io::PITCH.into(), Tensor::from_array(([1, frames], coarse.to_vec())).map_err(backend)?.into()));
                inputs.push((io::EXCITATION.into(), Tensor::from_array(([1, 1, excitation.len()], excitation)).map_err(backend)?.into()));
            }
            (true, None) => return Err(Error::invalid("this model needs pitch")),
            (false, _) => {}
        }
        let outputs = self.session.run(inputs).map_err(backend)?;
        Ok(first_output(&outputs, io::AUDIO)?.1)
    }
}
