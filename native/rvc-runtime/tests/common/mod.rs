//! Shared helpers for the conformance tests: where the reference fixtures live and how
//! to read them.
#![allow(dead_code, clippy::chunks_exact_to_as_chunks)]

use std::path::{Path, PathBuf};

/// The reference directory prepared by `reference/setup_reference.py`.
pub fn reference_dir() -> PathBuf {
    if let Some(path) = std::env::var_os("RVC_REFERENCE_DIR") {
        return PathBuf::from(path);
    }
    let cache = std::env::var_os("XDG_CACHE_HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".cache"));
    cache.join("vrct-vox").join("rvc-reference")
}

/// The fixture folder of a case, or `None` (with a notice) when it has not been generated.
/// Set `RVC_REQUIRE_REFERENCE=1` to make a missing fixture a failure instead of a skip.
pub fn case(name: &str) -> Option<PathBuf> {
    let folder = reference_dir().join("fixtures").join(name);
    if folder.join("case.json").is_file() {
        return Some(folder);
    }
    if std::env::var_os("RVC_REQUIRE_REFERENCE").is_some() {
        panic!("reference fixture `{name}` is missing; run reference/setup_reference.py, export_hubert_onnx.py and dump_reference.py");
    }
    eprintln!("SKIPPED: reference fixture `{name}` is missing (see native/rvc-runtime/README.md)");
    None
}

pub fn case_json(folder: &Path) -> serde_json::Value {
    serde_json::from_str(&std::fs::read_to_string(folder.join("case.json")).unwrap()).unwrap()
}

/// A NumPy array file: its shape and raw little-endian payload.
pub struct Npy {
    pub shape: Vec<usize>,
    descr: String,
    data: Vec<u8>,
}

pub fn npy(path: &Path) -> Npy {
    let bytes = std::fs::read(path).unwrap_or_else(|error| panic!("{}: {error}", path.display()));
    assert_eq!(&bytes[..6], b"\x93NUMPY", "not a NumPy file");
    let (header_len, start) = if bytes[6] == 1 { (u16::from_le_bytes([bytes[8], bytes[9]]) as usize, 10) } else { (u32::from_le_bytes(bytes[8..12].try_into().unwrap()) as usize, 12) };
    let header = std::str::from_utf8(&bytes[start..start + header_len]).unwrap();
    let field = |key: &str| header.split(key).nth(1).unwrap();
    let descr = field("'descr':").split('\'').nth(1).unwrap().to_string();
    assert!(field("'fortran_order':").trim_start().starts_with("False"));
    let shape = field("'shape':").split('(').nth(1).unwrap().split(')').next().unwrap();
    let shape = shape.split(',').filter_map(|part| part.trim().parse().ok()).collect();
    Npy { shape, descr, data: bytes[start + header_len..].to_vec() }
}

impl Npy {
    pub fn f32(&self) -> Vec<f32> {
        match self.descr.as_str() {
            "<f4" => self.data.chunks_exact(4).map(|c| f32::from_le_bytes(c.try_into().unwrap())).collect(),
            "<f8" => self.f64().into_iter().map(|x| x as f32).collect(),
            "<i2" => self.data.chunks_exact(2).map(|c| i16::from_le_bytes([c[0], c[1]]) as f32).collect(),
            other => panic!("unexpected dtype {other}"),
        }
    }

    pub fn f64(&self) -> Vec<f64> {
        match self.descr.as_str() {
            "<f8" => self.data.chunks_exact(8).map(|c| f64::from_le_bytes(c.try_into().unwrap())).collect(),
            "<f4" => self.f32().into_iter().map(|x| x as f64).collect(),
            other => panic!("unexpected dtype {other}"),
        }
    }

    pub fn i64(&self) -> Vec<i64> {
        assert_eq!(self.descr, "<i8");
        self.data.chunks_exact(8).map(|c| i64::from_le_bytes(c.try_into().unwrap())).collect()
    }
}

/// `|a - b| / |b|` over the whole arrays.
pub fn relative_error(found: &[f32], expected: &[f32]) -> f64 {
    assert_eq!(found.len(), expected.len(), "length mismatch");
    let difference: f64 = found.iter().zip(expected).map(|(a, b)| (*a as f64 - *b as f64).powi(2)).sum();
    let norm: f64 = expected.iter().map(|b| (*b as f64).powi(2)).sum();
    (difference / norm).sqrt()
}

pub fn max_abs_error(found: &[f32], expected: &[f32]) -> f32 {
    assert_eq!(found.len(), expected.len(), "length mismatch");
    found.iter().zip(expected).map(|(a, b)| (a - b).abs()).fold(0.0, f32::max)
}

/// Mean and minimum cosine similarity between corresponding rows.
pub fn cosine(found: &[f32], expected: &[f32], width: usize) -> (f64, f64) {
    let (mut total, mut lowest, mut rows) = (0.0, f64::INFINITY, 0);
    for (a, b) in found.chunks_exact(width).zip(expected.chunks_exact(width)) {
        let dot: f64 = a.iter().zip(b).map(|(x, y)| *x as f64 * *y as f64).sum();
        let norm = |v: &[f32]| v.iter().map(|x| (*x as f64).powi(2)).sum::<f64>().sqrt();
        let similarity = dot / (norm(a) * norm(b));
        total += similarity;
        lowest = lowest.min(similarity);
        rows += 1;
    }
    (total / rows as f64, lowest)
}
