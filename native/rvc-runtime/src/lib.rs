//! Inference-only RVC voice conversion for VRCT-VOX.
//!
//! The processing follows `docs/superpowers/specs/2026-11-15-rvc-inference-runtime-design.md`.
//! Voice models (`.pth`) and retrieval indexes (`.index`) are read as they are; the three
//! networks run on ONNX Runtime. See the crate README for the assets and how the output is
//! checked against the reference implementation.
// Slices of run-time length are chunked throughout; the fixed-size form reads no better here.
#![allow(clippy::chunks_exact_to_as_chunks)]

pub mod audio;
pub mod backend;
pub mod error;
pub mod f0;
pub mod filter;
pub mod index;
pub mod model;
pub mod noise;
pub mod onnx;
pub mod pipeline;
pub mod pth;
pub mod synth;

pub use backend::{Device, FeatureExtractor, Rmvpe, Synthesizer};
pub use error::{Error, Result};
pub use index::FeatureIndex;
pub use model::{Version, VoiceModel};
pub use noise::NoiseMode;
pub use pipeline::{Chunking, Converted, Converter, Options, Trace};
