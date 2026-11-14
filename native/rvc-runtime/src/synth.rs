//! The synthesizer (specification section 9): a VITS-style generator with an optional
//! neural source filter, expressed as an ONNX graph built directly from a voice model's
//! weights. The layout is recovered from the structure parameters and the shapes of the
//! stored tensors, so the user's `.pth` runs as it is, with no conversion step.
//!
//! Inference (pitch-enabled variant):
//!
//! ```text
//! g       = speaker_embedding[sid]
//! m, logs = prior_encoder(features, coarse_pitch)
//! z_p     = m + exp(logs) * noise * 0.66666
//! z       = flow^-1(z_p, g)
//! audio   = decoder(z, excitation, g)
//! ```
//!
//! Everything random (`noise`, and the noise inside `excitation`) is a graph input, so
//! the graph itself is deterministic.

use crate::error::{Error, Result};
use crate::model::VoiceModel;
use crate::onnx::{Attr, Dim, Graph};
use crate::pth::Tensor;

const KIND: &str = "voice model";
/// Scale of the prior noise at inference.
const NOISE_SCALE: f32 = 0.66666;
const LAYER_NORM_EPSILON: f32 = 1e-5;
const SLOPE: f32 = 0.1;

/// Names of the graph's inputs and output.
pub mod io {
    /// `[1, frames, feature_dim]` content features at 100 frames per second.
    pub const FEATURES: &str = "features";
    /// `[1, frames]` quantised pitch (pitch-enabled models only).
    pub const PITCH: &str = "pitch";
    /// `[1, frames, inter_channels]` standard normal noise for the prior.
    pub const NOISE: &str = "noise";
    /// `[1, 1, frames * samples_per_frame]` source excitation (pitch-enabled models only).
    pub const EXCITATION: &str = "excitation";
    /// `[1]` speaker number.
    pub const SPEAKER: &str = "speaker";
    /// `[1, 1, frames * samples_per_frame]` waveform.
    pub const AUDIO: &str = "audio";
}

struct Builder<'a> {
    model: &'a VoiceModel,
    graph: Graph,
}

/// Builds the ONNX model for a voice model.
pub fn build_graph(model: &VoiceModel) -> Result<Vec<u8>> {
    let mut builder = Builder { model, graph: Graph::new() };
    builder.build()?;
    Ok(builder.graph.into_model())
}

fn bad(detail: impl std::fmt::Display) -> Error {
    Error::format(KIND, detail)
}

impl Builder<'_> {
    fn has(&self, name: &str) -> bool {
        self.model.weights.contains_key(name)
    }

    /// A stored tensor as a graph constant.
    fn constant(&mut self, name: &str) -> Result<String> {
        let tensor = self.model.tensor(name)?;
        Ok(self.graph.f32s(&tensor.shape, &tensor.data))
    }

    /// The weight of a convolution, undoing weight normalisation when the model stores
    /// direction and magnitude separately (`w = g * v / |v|`, norm per first-axis slice).
    fn weight(&self, prefix: &str) -> Result<Tensor> {
        if let Some(weight) = self.model.weights.get(&format!("{prefix}.weight")) {
            return Ok(weight.clone());
        }
        let pair = [("weight_g", "weight_v"), ("parametrizations.weight.original0", "parametrizations.weight.original1")]
            .iter()
            .find_map(|(g, v)| Some((self.model.weights.get(&format!("{prefix}.{g}"))?, self.model.weights.get(&format!("{prefix}.{v}"))?)));
        let (magnitude, direction) = pair.ok_or_else(|| bad(format!("missing weight {prefix}")))?;
        let rows = *direction.shape.first().ok_or_else(|| bad(format!("weight {prefix} has no shape")))?;
        if rows == 0 || magnitude.len() != rows {
            return Err(bad(format!("weight {prefix} has an inconsistent magnitude")));
        }
        let width = direction.len() / rows;
        let mut data = Vec::with_capacity(direction.len());
        for (row, &scale) in direction.data.chunks_exact(width).zip(&magnitude.data) {
            let norm = row.iter().map(|&x| x as f64 * x as f64).sum::<f64>().sqrt();
            data.extend(row.iter().map(|&x| (x as f64 * scale as f64 / norm) as f32));
        }
        Ok(Tensor { shape: direction.shape.clone(), data })
    }

    fn bias(&mut self, prefix: &str) -> Result<Option<String>> {
        let name = format!("{prefix}.bias");
        if self.has(&name) {
            self.constant(&name).map(Some)
        } else {
            Ok(None)
        }
    }

    /// A convolution over `[1, channels, time]` with "same" padding for odd kernels.
    fn conv(&mut self, x: &str, prefix: &str, dilation: usize) -> Result<String> {
        let weight = self.weight(prefix)?;
        let kernel = *weight.shape.get(2).ok_or_else(|| bad(format!("{prefix} is not a 1-D convolution")))?;
        let total = (kernel - 1) * dilation;
        let w = self.graph.f32s(&weight.shape, &weight.data);
        let bias = self.bias(prefix)?;
        Ok(self.graph.conv(x, &w, bias.as_deref(), kernel, 1, dilation, (total / 2, total - total / 2)))
    }

    /// A 1x1 convolution applied as a matrix product over `[1, time, channels]`.
    fn linear(&mut self, x: &str, prefix: &str) -> Result<String> {
        let weight = self.weight(prefix)?;
        let (out, input) = (weight.shape[0], weight.len() / weight.shape[0]);
        let mut transposed = vec![0.0f32; weight.len()];
        for o in 0..out {
            for i in 0..input {
                transposed[i * out + o] = weight.data[o * input + i];
            }
        }
        let w = self.graph.f32s(&[input, out], &transposed);
        let product = self.graph.matmul(x, &w);
        match self.bias(prefix)? {
            Some(bias) => Ok(self.graph.add(&product, &bias)),
            None => Ok(product),
        }
    }

    fn build(&mut self) -> Result<()> {
        let config = self.model.config.clone();
        let feature_dim = self.model.version.feature_dim();
        let frames = Dim::Named("frames");
        let features = self.graph.input_f32(io::FEATURES, &[Dim::Fixed(1), frames, Dim::Fixed(feature_dim)]);
        let pitch = self.model.f0.then(|| self.graph.input_i64(io::PITCH, &[Dim::Fixed(1), frames]));
        let noise = self.graph.input_f32(io::NOISE, &[Dim::Fixed(1), frames, Dim::Fixed(config.inter_channels)]);
        let excitation = self.model.f0.then(|| self.graph.input_f32(io::EXCITATION, &[Dim::Fixed(1), Dim::Fixed(1), Dim::Named("samples")]));
        let speaker = self.graph.input_i64(io::SPEAKER, &[Dim::Fixed(1)]);

        // Speaker embedding as [1, gin, 1].
        let table = self.constant("emb_g.weight")?;
        let embedding = self.graph.op("Gather", &[&table, &speaker], vec![Attr::Int("axis", 0)]);
        let axis = self.graph.i64s(&[2]);
        let g = self.graph.op("Unsqueeze", &[&embedding, &axis], vec![]);

        let stats = self.prior_encoder(&features, pitch.as_deref())?;
        let inter = config.inter_channels as i64;
        let mean = self.graph.slice(&stats, &[0], &[inter], &[2]);
        let log_scale = self.graph.slice(&stats, &[inter], &[2 * inter], &[2]);
        let scale = self.graph.op("Exp", &[&log_scale], vec![]);
        let noise_scale = self.graph.scalar(NOISE_SCALE);
        let scaled = self.graph.mul(&noise, &noise_scale);
        let spread = self.graph.mul(&scale, &scaled);
        let z_p = self.graph.add(&mean, &spread);
        let z_p = self.graph.transpose(&z_p, &[0, 2, 1]);

        let z = self.inverse_flow(&z_p, &g)?;
        let audio = self.decoder(&z, excitation.as_deref(), &g)?;
        self.graph.output_f32(io::AUDIO, &audio, &[Dim::Fixed(1), Dim::Fixed(1), Dim::Named("samples")]);
        Ok(())
    }

    /// Features (and pitch) to the mean and log-scale of the prior, `[1, frames, 2 * inter]`.
    fn prior_encoder(&mut self, features: &str, pitch: Option<&str>) -> Result<String> {
        let config = self.model.config.clone();
        let hidden = config.hidden_channels;
        let mut x = self.linear(features, "enc_p.emb_phone")?;
        if let Some(pitch) = pitch {
            let table = self.constant("enc_p.emb_pitch.weight")?;
            let embedded = self.graph.op("Gather", &[&table, pitch], vec![Attr::Int("axis", 0)]);
            x = self.graph.add(&x, &embedded);
        }
        let gain = self.graph.scalar((hidden as f32).sqrt());
        x = self.graph.mul(&x, &gain);
        x = self.graph.leaky_relu(&x, SLOPE);

        // Sequence length as a one-element tensor, for the relative-position reshapes.
        let shape = self.graph.op("Shape", &[features], vec![]);
        let length = self.graph.slice(&shape, &[1], &[2], &[0]);
        for layer in 0..config.n_layers {
            let attended = self.attention(&x, &format!("enc_p.encoder.attn_layers.{layer}"), &length)?;
            let sum = self.graph.add(&x, &attended);
            x = self.layer_norm(&sum, &format!("enc_p.encoder.norm_layers_1.{layer}"))?;
            let fed = self.feed_forward(&x, &format!("enc_p.encoder.ffn_layers.{layer}"))?;
            let sum = self.graph.add(&x, &fed);
            x = self.layer_norm(&sum, &format!("enc_p.encoder.norm_layers_2.{layer}"))?;
        }
        self.linear(&x, "enc_p.proj")
    }

    fn layer_norm(&mut self, x: &str, prefix: &str) -> Result<String> {
        let gamma = self.constant(&format!("{prefix}.gamma"))?;
        let beta = self.constant(&format!("{prefix}.beta"))?;
        Ok(self.graph.op("LayerNormalization", &[x, &gamma, &beta], vec![Attr::Int("axis", -1), Attr::Float("epsilon", LAYER_NORM_EPSILON)]))
    }

    fn feed_forward(&mut self, x: &str, prefix: &str) -> Result<String> {
        let y = self.graph.transpose(x, &[0, 2, 1]);
        let y = self.conv(&y, &format!("{prefix}.conv_1"), 1)?;
        let y = self.graph.op("Relu", &[&y], vec![]);
        let y = self.conv(&y, &format!("{prefix}.conv_2"), 1)?;
        Ok(self.graph.transpose(&y, &[0, 2, 1]))
    }

    /// Multi-head self-attention with learned relative-position terms for keys and values
    /// within a window of `w` frames either side. `x` is `[1, frames, hidden]`.
    fn attention(&mut self, x: &str, prefix: &str, length: &str) -> Result<String> {
        let heads = self.model.config.n_heads;
        let hidden = self.model.config.hidden_channels;
        let width = hidden / heads;
        let rel_k = self.model.tensor(&format!("{prefix}.emb_rel_k"))?.clone();
        let rel_v = self.model.tensor(&format!("{prefix}.emb_rel_v"))?.clone();
        // [shared heads = 1, 2w + 1, width]
        if rel_k.shape.len() != 3 || rel_k.shape[0] != 1 || rel_k.shape[2] != width || rel_k.shape[1] % 2 == 0 || rel_v.shape != rel_k.shape {
            return Err(Error::unsupported(KIND, "relative position embeddings that are not shared across heads"));
        }
        let span = rel_k.shape[1];
        let window = (span / 2) as i64;
        let (h, span_i) = (heads as i64, span as i64);

        let split = self.graph.i64s(&[1, -1, h, width as i64]);
        let project = |builder: &mut Self, name: &str| -> Result<String> {
            let projected = builder.linear(x, &format!("{prefix}.{name}"))?;
            let reshaped = builder.graph.reshape(&projected, &split);
            Ok(builder.graph.transpose(&reshaped, &[0, 2, 1, 3]))
        };
        let query = project(self, "conv_q")?;
        let key = project(self, "conv_k")?;
        let value = project(self, "conv_v")?;
        let scale = self.graph.scalar(1.0 / (width as f32).sqrt());
        let query = self.graph.mul(&query, &scale);

        let key_t = self.graph.transpose(&key, &[0, 1, 3, 2]);
        let mut scores = self.graph.matmul(&query, &key_t);

        // Key term: logits against the 2w+1 relative embeddings, [1, h, L, 2w+1], moved so
        // that column c of row i lands on column i + c - w. Padding each row to L + 2w + 1
        // and re-reading the flattened rows at width L + 2w shifts row i right by i.
        let mut rel_k_t = vec![0.0f32; span * width];
        for r in 0..span {
            for c in 0..width {
                rel_k_t[c * span + r] = rel_k.data[r * width + c];
            }
        }
        let rel_k_t = self.graph.f32s(&[width, span], &rel_k_t);
        let relative = self.graph.matmul(&query, &rel_k_t);
        let zeros7 = self.graph.i64s(&[0; 7]);
        let pads = self.graph.concat(&[&zeros7, length], 0);
        let padded = self.graph.pad(&relative, &pads);
        let flat_shape = self.graph.i64s(&[1, h, -1]);
        let flat = self.graph.reshape(&padded, &flat_shape);
        let tail = self.graph.i64s(&[0, 0, 0, 0, 0, 2 * window]);
        let flat = self.graph.pad(&flat, &tail);
        let one = self.graph.i64s(&[1]);
        let two_w = self.graph.i64s(&[2 * window]);
        let w = self.graph.i64s(&[window]);
        let rows = self.graph.add(length, &one);
        let columns = self.graph.add(length, &two_w);
        let head = self.graph.i64s(&[1, h]);
        let skewed_shape = self.graph.concat(&[&head, &rows, &columns], 0);
        let skewed = self.graph.reshape(&flat, &skewed_shape);
        let starts = self.graph.i64s(&[0, window]);
        let end_column = self.graph.add(length, &w);
        let ends = self.graph.concat(&[length, &end_column], 0);
        let axes = self.graph.i64s(&[2, 3]);
        let absolute = self.graph.op("Slice", &[&skewed, &starts, &ends, &axes], vec![]);
        scores = self.graph.add(&scores, &absolute);

        let weights = self.graph.op("Softmax", &[&scores], vec![Attr::Int("axis", -1)]);
        let mut output = self.graph.matmul(&weights, &value);

        // Value term: the attention weights at relative offsets -w..=w, [1, h, L, 2w+1],
        // times the value embeddings. The inverse shift: pad w columns either side, then
        // re-read the flattened rows at width L + 2w + 1 so row i moves left by i.
        let side = self.graph.i64s(&[0, 0, 0, window, 0, 0, 0, window]);
        let padded = self.graph.pad(&weights, &side);
        let flat = self.graph.reshape(&padded, &flat_shape);
        let zeros5 = self.graph.i64s(&[0; 5]);
        let pads = self.graph.concat(&[&zeros5, length], 0);
        let flat = self.graph.pad(&flat, &pads);
        let span_plus = self.graph.i64s(&[span_i]);
        let columns = self.graph.add(length, &span_plus);
        let skewed_shape = self.graph.concat(&[&head, length, &columns], 0);
        let skewed = self.graph.reshape(&flat, &skewed_shape);
        let relative_weights = self.graph.slice(&skewed, &[0], &[span_i], &[3]);
        let rel_v = self.graph.f32s(&[span, width], &rel_v.data);
        let relative_values = self.graph.matmul(&relative_weights, &rel_v);
        output = self.graph.add(&output, &relative_values);

        let merged = self.graph.transpose(&output, &[0, 2, 1, 3]);
        let merge = self.graph.i64s(&[1, -1, hidden as i64]);
        let merged = self.graph.reshape(&merged, &merge);
        self.linear(&merged, &format!("{prefix}.conv_o"))
    }

    /// The normalising flow run backwards: `[1, inter, frames]` prior sample to latent.
    fn inverse_flow(&mut self, z_p: &str, g: &str) -> Result<String> {
        let inter = self.model.config.inter_channels;
        let half = (inter / 2) as i64;
        // Coupling layers sit at even positions; each is followed by a channel reversal.
        let mut layers = Vec::new();
        while self.has(&format!("flow.flows.{}.pre.weight", layers.len() * 2)) {
            layers.push(layers.len() * 2);
        }
        if layers.is_empty() {
            return Err(bad("no flow layers"));
        }
        let reversed: Vec<i64> = (0..inter as i64).rev().collect();
        let reversed = self.graph.i64s(&reversed);
        let mut x = z_p.to_string();
        for &layer in layers.iter().rev() {
            let prefix = format!("flow.flows.{layer}");
            x = self.graph.op("Gather", &[&x, &reversed], vec![Attr::Int("axis", 1)]);
            let kept = self.graph.slice(&x, &[0], &[half], &[1]);
            let changed = self.graph.slice(&x, &[half], &[2 * half], &[1]);
            let hidden = self.conv(&kept, &format!("{prefix}.pre"), 1)?;
            let hidden = self.wavenet(&hidden, g, &format!("{prefix}.enc"))?;
            let mean = self.conv(&hidden, &format!("{prefix}.post"), 1)?;
            if self.model.tensor(&format!("{prefix}.post.weight"))?.shape[0] as i64 != half {
                return Err(Error::unsupported(KIND, "flow layers that also predict a scale"));
            }
            let restored = self.graph.sub(&changed, &mean);
            x = self.graph.concat(&[&kept, &restored], 1);
        }
        Ok(x)
    }

    /// Gated dilated convolutions conditioned on the speaker, with skip connections.
    fn wavenet(&mut self, x: &str, g: &str, prefix: &str) -> Result<String> {
        let mut layers = 0;
        while self.has(&format!("{prefix}.in_layers.{layers}.bias")) {
            layers += 1;
        }
        let channels = self.model.tensor(&format!("{prefix}.in_layers.0.bias"))?.len() as i64 / 2;
        let condition = self.conv(g, &format!("{prefix}.cond_layer"), 1)?;
        let mut x = x.to_string();
        let mut output: Option<String> = None;
        for layer in 0..layers {
            let gated = self.conv(&x, &format!("{prefix}.in_layers.{layer}"), 1)?;
            let offset = layer as i64 * 2 * channels;
            let local = self.graph.slice(&condition, &[offset], &[offset + 2 * channels], &[1]);
            let gated = self.graph.add(&gated, &local);
            let left = self.graph.slice(&gated, &[0], &[channels], &[1]);
            let right = self.graph.slice(&gated, &[channels], &[2 * channels], &[1]);
            let left = self.graph.op("Tanh", &[&left], vec![]);
            let right = self.graph.op("Sigmoid", &[&right], vec![]);
            let activated = self.graph.mul(&left, &right);
            let mixed = self.conv(&activated, &format!("{prefix}.res_skip_layers.{layer}"), 1)?;
            // Every layer but the last feeds half of its output back into the stack.
            let skip = if layer + 1 < layers {
                let residual = self.graph.slice(&mixed, &[0], &[channels], &[1]);
                x = self.graph.add(&x, &residual);
                self.graph.slice(&mixed, &[channels], &[2 * channels], &[1])
            } else {
                mixed
            };
            output = Some(match output {
                Some(total) => self.graph.add(&total, &skip),
                None => skip,
            });
        }
        output.ok_or_else(|| bad("flow layer without convolutions"))
    }

    /// Latent to waveform: transposed-convolution upsampling with residual blocks, and
    /// for pitch-enabled models the excitation injected at every resolution.
    fn decoder(&mut self, z: &str, excitation: Option<&str>, g: &str) -> Result<String> {
        let config = self.model.config.clone();
        let mut x = self.conv(z, "dec.conv_pre", 1)?;
        let condition = self.conv(g, "dec.cond", 1)?;
        x = self.graph.add(&x, &condition);

        let source = match excitation {
            Some(excitation) => {
                let weight = self.model.tensor("dec.m_source.l_linear.weight")?;
                if weight.len() != 1 {
                    return Err(Error::unsupported(KIND, "source modules with harmonics"));
                }
                let gain = self.graph.scalar(weight.data[0]);
                let offset = self.graph.scalar(self.model.tensor("dec.m_source.l_linear.bias")?.data[0]);
                let scaled = self.graph.mul(excitation, &gain);
                let shifted = self.graph.add(&scaled, &offset);
                Some(self.graph.op("Tanh", &[&shifted], vec![]))
            }
            None => None,
        };

        let blocks = config.resblock_kernel_sizes.len();
        for (stage, (&rate, &kernel)) in config.upsample_rates.iter().zip(&config.upsample_kernel_sizes).enumerate() {
            x = self.graph.leaky_relu(&x, SLOPE);
            let prefix = format!("dec.ups.{stage}");
            let weight = self.weight(&prefix)?;
            if weight.shape.get(2) != Some(&kernel) || kernel < rate {
                return Err(bad(format!("{prefix} does not match the upsample kernel size")));
            }
            let w = self.graph.f32s(&weight.shape, &weight.data);
            let bias = self.bias(&prefix)?;
            x = self.graph.conv_transpose(&x, &w, bias.as_deref(), kernel, rate, (kernel - rate) / 2);
            if let Some(source) = &source {
                // The excitation is brought down to this stage's rate by a strided convolution.
                let prefix = format!("dec.noise_convs.{stage}");
                let weight = self.weight(&prefix)?;
                let stride: usize = config.upsample_rates[stage + 1..].iter().product();
                let kernel = weight.shape[2];
                let pad = if kernel == 1 { 0 } else { stride / 2 };
                let w = self.graph.f32s(&weight.shape, &weight.data);
                let bias = self.bias(&prefix)?;
                let injected = self.graph.conv(source, &w, bias.as_deref(), kernel, stride, 1, (pad, pad));
                x = self.graph.add(&x, &injected);
            }
            let mut total: Option<String> = None;
            for block in 0..blocks {
                let out = self.residual_block(&x, &format!("dec.resblocks.{}", stage * blocks + block), &config.resblock_dilation_sizes[block])?;
                total = Some(match total {
                    Some(sum) => self.graph.add(&sum, &out),
                    None => out,
                });
            }
            let share = self.graph.scalar(1.0 / blocks as f32);
            x = self.graph.mul(&total.unwrap(), &share);
        }
        x = self.graph.leaky_relu(&x, 0.01);
        x = self.conv(&x, "dec.conv_post", 1)?;
        Ok(self.graph.op("Tanh", &[&x], vec![]))
    }

    fn residual_block(&mut self, x: &str, prefix: &str, dilations: &[usize]) -> Result<String> {
        let mut x = x.to_string();
        let paired = self.has(&format!("{prefix}.convs1.0.bias"));
        for (index, &dilation) in dilations.iter().enumerate() {
            let mut y = self.graph.leaky_relu(&x, SLOPE);
            if paired {
                // Type "1": a dilated convolution followed by an undilated one.
                y = self.conv(&y, &format!("{prefix}.convs1.{index}"), dilation)?;
                y = self.graph.leaky_relu(&y, SLOPE);
                y = self.conv(&y, &format!("{prefix}.convs2.{index}"), 1)?;
            } else {
                // Type "2": a single dilated convolution per step.
                y = self.conv(&y, &format!("{prefix}.convs.{index}"), dilation)?;
            }
            x = self.graph.add(&x, &y);
        }
        Ok(x)
    }
}
