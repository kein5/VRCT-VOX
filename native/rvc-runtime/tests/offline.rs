//! Tests that need no downloads: the committed fixtures under `tests/data` (written by
//! `reference/make_test_data.py`) hold tiny random-weight voice models, the reference's
//! output for them with all noise set to zero, and a small FAISS index with the
//! neighbours FAISS returns.
#![allow(clippy::chunks_exact_to_as_chunks)]
mod common;

use std::path::PathBuf;

use common::{npy, relative_error};
use rvc_runtime::noise::Generator;
use rvc_runtime::{Device, Error, FeatureIndex, NoiseMode, Synthesizer, Version, VoiceModel};

fn data(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/data").join(name)
}

#[test]
fn voice_model_files_are_read_as_the_specification_says() {
    let model = VoiceModel::load(&data("tiny_v2_f0_40k.pth")).unwrap();
    assert_eq!((model.version, model.f0), (Version::V2, true));
    let config = &model.config;
    assert_eq!(config.sample_rate, 40_000);
    assert_eq!(config.upsample_rates, [10, 10, 2, 2]);
    assert_eq!(config.resblock_dilation_sizes, vec![vec![1, 3, 5]; 3]);
    assert_eq!(config.resblock, "1");
    // The speaker count comes from the embedding table.
    assert_eq!(config.spk_embed_dim, model.tensor("emb_g.weight").unwrap().shape[0]);
    // Half-precision storage is widened exactly.
    let phone = model.tensor("enc_p.emb_phone.weight").unwrap();
    assert_eq!(phone.shape, [8, 768]);
    assert!(phone.data.iter().all(|value| value.is_finite()));

    let model = VoiceModel::load(&data("tiny_v1_nof0_32k.pth")).unwrap();
    assert_eq!((model.version, model.f0, model.config.sample_rate), (Version::V1, false, 32_000));
    assert_eq!(model.config.resblock, "2");
}

#[test]
fn synthesizer_reproduces_the_reference_for_tiny_models() {
    for (name, frames) in [("tiny_v2_f0_40k", 5), ("tiny_v2_f0_40k", 24), ("tiny_v1_nof0_32k", 5), ("tiny_v1_nof0_32k", 24)] {
        let model = VoiceModel::load(&data(&format!("{name}.pth"))).unwrap();
        let mut synthesizer = Synthesizer::new(&model, Device::Cpu).unwrap();
        let array = |kind: &str| npy(&data(&format!("{name}_{frames}_{kind}.npy")));
        let features = array("features").f32();
        let tracks = model.f0.then(|| (array("coarse").i64(), array("hz").f32()));
        let expected = array("audio").f32();
        let found = synthesizer.synthesize(&features, tracks.as_ref().map(|(coarse, hz)| (&coarse[..], &hz[..])), 1, &mut Generator::new(NoiseMode::Zero)).unwrap();
        assert_eq!(found.len(), frames * model.config.samples_per_frame());
        let error = relative_error(&found, &expected);
        assert!(error < 1e-4, "{name} at {frames} frames: relative error {error}");
    }
}

#[test]
fn synthesizer_is_reproducible_with_a_seed_and_checks_its_inputs() {
    let model = VoiceModel::load(&data("tiny_v2_f0_40k.pth")).unwrap();
    let mut synthesizer = Synthesizer::new(&model, Device::Cpu).unwrap();
    let features = npy(&data("tiny_v2_f0_40k_24_features.npy")).f32();
    let (coarse, hz) = (npy(&data("tiny_v2_f0_40k_24_coarse.npy")).i64(), npy(&data("tiny_v2_f0_40k_24_hz.npy")).f32());
    let mut run = |mode: NoiseMode| synthesizer.synthesize(&features, Some((&coarse, &hz)), 0, &mut Generator::new(mode)).unwrap();
    let first = run(NoiseMode::Seeded(3));
    assert_eq!(first, run(NoiseMode::Seeded(3)));
    assert_ne!(first, run(NoiseMode::Seeded(4)));
    assert_ne!(first, run(NoiseMode::Zero));
    assert!(matches!(synthesizer.synthesize(&features, None, 0, &mut Generator::new(NoiseMode::Zero)), Err(Error::Invalid(_))));
    assert!(matches!(synthesizer.synthesize(&features, Some((&coarse, &hz)), 99, &mut Generator::new(NoiseMode::Zero)), Err(Error::Invalid(_))));
    assert!(matches!(synthesizer.synthesize(&features[..10], Some((&coarse, &hz)), 0, &mut Generator::new(NoiseMode::Zero)), Err(Error::Invalid(_))));
}

#[test]
fn inverted_file_index_returns_what_faiss_returns() {
    let index = FeatureIndex::load(&data("tiny_ivf.index")).unwrap();
    assert_eq!((index.dim(), index.len()), (16, 600));
    let queries = npy(&data("tiny_ivf_queries.npy")).f32();
    let (ids, distances) = (npy(&data("tiny_ivf_ids.npy")).i64(), npy(&data("tiny_ivf_distances.npy")).f32());
    for (frame, query) in queries.chunks_exact(16).enumerate() {
        let found = index.search(query, 8);
        let expected: Vec<i64> = ids[frame * 8..(frame + 1) * 8].iter().copied().filter(|&id| id >= 0).collect();
        assert_eq!(found.iter().map(|neighbour| neighbour.id).collect::<Vec<_>>(), expected, "query {frame}");
        for (neighbour, expected) in found.iter().zip(&distances[frame * 8..]) {
            assert!((neighbour.distance - expected).abs() <= 1e-4 * expected.max(1.0));
        }
    }
}

#[test]
fn flat_index_loads_and_a_trained_only_index_is_refused() {
    let index = FeatureIndex::load(&data("tiny_flat.index")).unwrap();
    assert_eq!((index.dim(), index.len()), (16, 50));
    assert!(matches!(FeatureIndex::load(&data("tiny_trained_only.index")), Err(Error::Invalid(_))));
}

#[test]
fn a_model_file_that_names_other_code_is_refused() {
    // A pickle that asks for `os.system`: the reader must refuse it, not run it.
    let pickle = b"\x80\x02cos\nsystem\nq\x00X\x02\x00\x00\x00idq\x01\x85q\x02Rq\x03.";
    let mut zip = Vec::new();
    let name = b"archive/data.pkl";
    zip.extend(b"PK\x03\x04\x14\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00");
    zip.extend((pickle.len() as u32).to_le_bytes());
    zip.extend((pickle.len() as u32).to_le_bytes());
    zip.extend((name.len() as u16).to_le_bytes());
    zip.extend(0u16.to_le_bytes());
    zip.extend(name);
    zip.extend(pickle);
    let directory = zip.len();
    zip.extend(b"PK\x01\x02\x14\x00\x14\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00");
    zip.extend((pickle.len() as u32).to_le_bytes());
    zip.extend((pickle.len() as u32).to_le_bytes());
    zip.extend((name.len() as u16).to_le_bytes());
    zip.extend([0u8; 12]);
    zip.extend(0u32.to_le_bytes());
    zip.extend(name);
    let size = zip.len() - directory;
    zip.extend(b"PK\x05\x06\x00\x00\x00\x00\x01\x00\x01\x00");
    zip.extend((size as u32).to_le_bytes());
    zip.extend((directory as u32).to_le_bytes());
    zip.extend(0u16.to_le_bytes());
    match VoiceModel::from_bytes(&zip) {
        Err(Error::Unsupported { detail, .. }) => assert!(detail.contains("os.system"), "{detail}"),
        other => panic!("expected the file to be refused, got {:?}", other.map(|_| ())),
    }
}
