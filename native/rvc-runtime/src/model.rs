//! The voice model file: structure parameters, weights and the two flags that select
//! the synthesizer variant (specification section 3).

use std::collections::HashMap;
use std::path::Path;

use crate::error::{Error, Result};
use crate::pth::{self, Tensor, Value};

const KIND: &str = "voice model";

/// Feature layout the model was trained on.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Version {
    /// 256-dimensional features (ninth encoder layer through the final projection).
    V1,
    /// 768-dimensional features (last encoder layer).
    V2,
}

impl Version {
    pub fn feature_dim(self) -> usize {
        match self {
            Version::V1 => 256,
            Version::V2 => 768,
        }
    }
}

/// The `config` array, in the order the specification lists it.
#[derive(Debug, Clone, PartialEq)]
pub struct SynthConfig {
    pub spec_channels: usize,
    pub segment_size: usize,
    pub inter_channels: usize,
    pub hidden_channels: usize,
    pub filter_channels: usize,
    pub n_heads: usize,
    pub n_layers: usize,
    pub kernel_size: usize,
    pub p_dropout: f64,
    pub resblock: String,
    pub resblock_kernel_sizes: Vec<usize>,
    pub resblock_dilation_sizes: Vec<Vec<usize>>,
    pub upsample_rates: Vec<usize>,
    pub upsample_initial_channel: usize,
    pub upsample_kernel_sizes: Vec<usize>,
    /// Number of speakers, taken from the speaker embedding table rather than the array.
    pub spk_embed_dim: usize,
    pub gin_channels: usize,
    pub sample_rate: u32,
}

impl SynthConfig {
    /// Output samples produced per 10 ms frame.
    pub fn samples_per_frame(&self) -> usize {
        self.upsample_rates.iter().product()
    }
}

/// A loaded voice model. The file is only read; nothing is written back.
#[derive(Debug, Clone)]
pub struct VoiceModel {
    pub config: SynthConfig,
    pub version: Version,
    /// Whether the synthesizer takes pitch (the NSF variant).
    pub f0: bool,
    pub weights: HashMap<String, Tensor>,
}

impl VoiceModel {
    pub fn load(path: &Path) -> Result<Self> {
        Self::from_checkpoint(pth::load(path)?)
    }

    pub fn from_bytes(bytes: &[u8]) -> Result<Self> {
        Self::from_checkpoint(pth::load_bytes(bytes)?)
    }

    fn from_checkpoint(checkpoint: Value) -> Result<Self> {
        let Value::Dict(entries) = checkpoint else {
            return Err(Error::format(KIND, "the checkpoint is not a dictionary"));
        };
        let mut config = None;
        let mut weight = None;
        let mut f0 = None;
        let mut version = None;
        for (key, value) in entries {
            match key.as_str() {
                Some("config") => config = Some(value),
                Some("weight") => weight = Some(value),
                Some("f0") => f0 = Some(value),
                Some("version") => version = Some(value),
                _ => {}
            }
        }
        let Some(Value::Dict(weight)) = weight else {
            return Err(Error::format(KIND, "no `weight` state dictionary (a training checkpoint, not an inference model?)"));
        };
        let mut weights = HashMap::with_capacity(weight.len());
        for (name, tensor) in weight {
            if let (Value::Str(name), Value::Tensor(tensor)) = (name, tensor) {
                weights.insert(name, tensor);
            }
        }
        // Missing flags default to pitch-enabled and v1, as the reference loader does.
        let f0 = match f0 {
            None | Some(Value::None) => true,
            Some(value) => value.as_i64().ok_or_else(|| Error::format(KIND, "`f0` is not a number"))? == 1,
        };
        let version = match version.as_ref().map(|value| value.as_str()) {
            None => Version::V1,
            Some(Some("v1")) => Version::V1,
            Some(Some("v2")) => Version::V2,
            Some(_) => return Err(Error::unsupported(KIND, "unknown model version")),
        };
        let config = config.ok_or_else(|| Error::format(KIND, "no `config` array"))?;
        let mut config = parse_config(&config)?;
        let speakers = weights.get("emb_g.weight").ok_or_else(|| Error::format(KIND, "no speaker embedding table"))?;
        config.spk_embed_dim = *speakers.shape.first().ok_or_else(|| Error::format(KIND, "speaker embedding table has no rows"))?;
        let model = VoiceModel { config, version, f0, weights };
        model.check()?;
        Ok(model)
    }

    fn check(&self) -> Result<()> {
        let config = &self.config;
        let rates: usize = config.samples_per_frame();
        if rates == 0 || rates * 100 != config.sample_rate as usize {
            return Err(Error::format(KIND, "upsample rates do not multiply to one hundredth of the sample rate"));
        }
        if config.upsample_rates.len() != config.upsample_kernel_sizes.len() {
            return Err(Error::format(KIND, "upsample rates and kernel sizes differ in length"));
        }
        if config.resblock_kernel_sizes.len() != config.resblock_dilation_sizes.len() || config.resblock_kernel_sizes.is_empty() {
            return Err(Error::format(KIND, "residual block kernel and dilation lists differ in length"));
        }
        if config.n_heads == 0 || !config.hidden_channels.is_multiple_of(config.n_heads) || config.inter_channels % 2 != 0 {
            return Err(Error::format(KIND, "inconsistent channel counts"));
        }
        let phone = self.tensor("enc_p.emb_phone.weight")?;
        if phone.shape != [config.hidden_channels, self.version.feature_dim()] {
            return Err(Error::format(KIND, "feature projection does not match the model version"));
        }
        if self.f0 != self.weights.contains_key("enc_p.emb_pitch.weight") {
            return Err(Error::format(KIND, "the `f0` flag disagrees with the weights"));
        }
        Ok(())
    }

    pub fn tensor(&self, name: &str) -> Result<&Tensor> {
        self.weights.get(name).ok_or_else(|| Error::format(KIND, format!("missing weight {name}")))
    }
}

fn parse_config(value: &Value) -> Result<SynthConfig> {
    let items = value.as_list().filter(|items| items.len() == 18).ok_or_else(|| Error::format(KIND, "`config` is not an 18-element array"))?;
    let bad = |index: usize| Error::format(KIND, format!("`config[{index}]` has an unexpected type"));
    let int = |index: usize| items[index].as_i64().and_then(|n| usize::try_from(n).ok()).ok_or_else(|| bad(index));
    let ints = |index: usize, value: &Value| -> Result<Vec<usize>> {
        let list = value.as_list().ok_or_else(|| bad(index))?;
        list.iter().map(|item| item.as_i64().and_then(|n| usize::try_from(n).ok()).ok_or_else(|| bad(index))).collect()
    };
    let resblock = match &items[9] {
        Value::Str(text) => text.clone(),
        other => other.as_i64().map(|n| n.to_string()).ok_or_else(|| bad(9))?,
    };
    let dilations = items[11].as_list().ok_or_else(|| bad(11))?.iter().map(|row| ints(11, row)).collect::<Result<Vec<_>>>()?;
    // The sample rate is normally a number; some exporters wrote the "40k" label instead.
    let sample_rate = match &items[17] {
        Value::Str(text) => text.strip_suffix('k').and_then(|n| n.parse::<u32>().ok()).map(|n| n * 1000).ok_or_else(|| bad(17))?,
        other => other.as_i64().and_then(|n| u32::try_from(n).ok()).ok_or_else(|| bad(17))?,
    };
    Ok(SynthConfig {
        spec_channels: int(0)?,
        segment_size: int(1)?,
        inter_channels: int(2)?,
        hidden_channels: int(3)?,
        filter_channels: int(4)?,
        n_heads: int(5)?,
        n_layers: int(6)?,
        kernel_size: int(7)?,
        p_dropout: items[8].as_f64().ok_or_else(|| bad(8))?,
        resblock,
        resblock_kernel_sizes: ints(10, &items[10])?,
        resblock_dilation_sizes: dilations,
        upsample_rates: ints(12, &items[12])?,
        upsample_initial_channel: int(13)?,
        upsample_kernel_sizes: ints(14, &items[14])?,
        spk_embed_dim: int(15)?,
        gin_channels: int(16)?,
        sample_rate,
    })
}
