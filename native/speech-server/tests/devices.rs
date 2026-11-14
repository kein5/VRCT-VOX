//! Which GPU "auto" and "gpu" start the bundled speech.cpp on, for any vendor, and the
//! check of the bundle itself.

use std::path::PathBuf;

use serde_json::{json, Value};
use vrct_speech_server::bundle::bundled_binary;
use vrct_speech_server::codes;
use vrct_speech_server::devices::{device_rows, list_gpus, parse_devices, preferred_gpu, resolve_device};
use vrct_speech_server::settings::device_allowed;

fn row(name: &str, description: &str, kind: &str, gigabytes: u64) -> Value {
    json!({"name": name, "description": description, "kind": kind, "memory_total": gigabytes << 30, "memory_free": gigabytes << 30})
}

fn cpu() -> Value {
    row("CPU", "12th Gen Intel(R) Core(TM) i7-1255U", "cpu", 32)
}

#[test]
fn a_separate_gpu_comes_first_for_every_vendor() {
    let cases = [
        // speech.cpp lists the integrated GPU first; a separate one is chosen whatever its vendor.
        (
            vec![
                row("Vulkan0", "Intel(R) Iris(R) Xe Graphics", "igpu", 16),
                row("Vulkan1", "NVIDIA GeForce RTX 3060 Ti", "gpu", 8),
                cpu(),
            ],
            Some("Vulkan1"),
        ),
        (
            vec![
                row("Vulkan0", "AMD Radeon(TM) Graphics", "igpu", 2),
                row("Vulkan1", "AMD Radeon RX 7800 XT", "gpu", 16),
                cpu(),
            ],
            Some("Vulkan1"),
        ),
        (
            vec![
                row("Vulkan0", "Intel(R) UHD Graphics 770", "igpu", 8),
                row("Vulkan1", "Intel(R) Arc(TM) B580 Graphics", "gpu", 12),
                cpu(),
            ],
            Some("Vulkan1"),
        ),
        // Two separate GPUs: the one with more memory. Equal ones: the first listed.
        (
            vec![row("Vulkan0", "AMD Radeon RX 6600", "gpu", 8), row("Vulkan1", "NVIDIA GeForce RTX 4090", "gpu", 24)],
            Some("Vulkan1"),
        ),
        (
            vec![row("Vulkan0", "AMD Radeon RX 6600", "gpu", 8), row("Vulkan1", "AMD Radeon RX 6600", "gpu", 8)],
            Some("Vulkan0"),
        ),
        // Only an integrated GPU (a laptop with Intel or AMD graphics only).
        (vec![row("Vulkan0", "AMD Radeon(TM) 780M", "igpu", 8), cpu()], Some("Vulkan0")),
        // The Direct3D 12 mapping layer and software rasterizers are not GPUs to compute on.
        (vec![row("Vulkan0", "Microsoft Direct3D12 (Intel(R) Iris(R) Xe Graphics)", "igpu", 8), cpu()], None),
        (vec![row("Vulkan0", "llvmpipe (LLVM 19.1.7, 256 bits)", "igpu", 8), cpu()], None),
        (vec![cpu()], None),
        (vec![], None),
    ];
    for (devices, chosen) in cases {
        assert_eq!(preferred_gpu(&devices).as_deref(), chosen, "{devices:?}");
    }
}

#[test]
fn rows_that_are_not_devices_are_ignored() {
    let rows = [
        Value::Null,
        json!("Vulkan0"),
        json!({"name": "Vulkan0; rm", "kind": "gpu"}),
        json!({"name": "Vulkan2", "description": "AMD Radeon RX 7600", "kind": "gpu", "memory_total": null}),
    ];
    assert_eq!(preferred_gpu(&rows).as_deref(), Some("Vulkan2"));
}

#[test]
fn only_auto_and_gpu_are_resolved() {
    let devices = [
        row("Vulkan0", "Intel(R) Iris(R) Xe Graphics", "igpu", 8),
        row("Vulkan1", "NVIDIA GeForce RTX 3060 Ti", "gpu", 8),
    ];
    assert_eq!(resolve_device("auto", Some(&devices)), "Vulkan1");
    assert_eq!(resolve_device("gpu", Some(&devices)), "Vulkan1");
    // A device the user named, and the CPU, are passed on as they are.
    assert_eq!(resolve_device("Vulkan0", Some(&devices)), "Vulkan0");
    assert_eq!(resolve_device("cpu", Some(&devices)), "cpu");
}

#[test]
fn without_a_gpu_or_a_device_list_the_choice_is_left_to_speech_cpp() {
    assert_eq!(resolve_device("auto", Some(&[cpu()])), "auto");
    assert_eq!(resolve_device("gpu", Some(&[])), "gpu");
    assert_eq!(resolve_device("auto", None), "auto");
}

#[test]
fn only_devices_that_cannot_compute_mean_the_cpu_for_auto() {
    // Windows with only Microsoft's Vulkan-on-Direct3D 12 layer: models load, then the first
    // request fails. "auto" runs on the CPU instead; "gpu" keeps failing with its notice.
    let layer = [
        row("Vulkan0", "Microsoft Direct3D12 (Intel(R) Iris(R) Xe Graphics)", "igpu", 8),
        row("Vulkan1", "Microsoft Direct3D12 (NVIDIA GeForce RTX 3060 Ti)", "gpu", 8),
        cpu(),
    ];
    assert_eq!(resolve_device("auto", Some(&layer)), "cpu");
    assert_eq!(resolve_device("gpu", Some(&layer)), "gpu");
}

#[test]
fn only_the_gpus_of_the_device_text_are_listed() {
    let text = "Vulkan0    igpu  Intel(R) Iris(R) Xe Graphics, 17.1 GB, 16.3 GB free\n\
                Vulkan1    gpu   NVIDIA GeForce RTX 3060 Ti, 8.6 GB, 7.8 GB free\r\n\
                CPU        cpu   12th Gen Intel(R) Core(TM) i7-1255U, 33.9 GB, 20.1 GB free\n";
    let listed: Vec<_> = parse_devices(text).into_iter().map(|gpu| (gpu.name, gpu.kind, gpu.label)).collect();
    let expected =
        [("Vulkan0", "igpu", "Intel(R) Iris(R) Xe Graphics"), ("Vulkan1", "gpu", "NVIDIA GeForce RTX 3060 Ti")];
    assert_eq!(listed, expected.map(|(name, kind, label)| (name.to_owned(), kind.to_owned(), label.to_owned())));
    // A comma in the label is part of it.
    assert_eq!(parse_devices("Vulkan3 gpu Vendor, Inc. Card, 8.0 GB, 1 GB free")[0].label, "Vendor, Inc. Card");
    for text in
        ["", "no devices\n", "Vulkan0 igpu\n", "Vulkan999 gpu X, 1 GB, 1 GB free\n", "Vulkan0 cpu X, 1 GB, 1 GB free\n"]
    {
        assert!(parse_devices(text).is_empty(), "{text:?}");
    }
}

#[test]
fn only_the_general_choices_and_named_gpus_are_devices() {
    for device in ["auto", "cpu", "gpu", "Vulkan0", "Vulkan1", "Vulkan99"] {
        assert!(device_allowed(device), "{device}");
    }
    for device in ["Vulkan", "Vulkan123", "vulkan1", "CUDA0", "--device", "Vulkan1 --port", "Vulkan1\n", ""] {
        assert!(!device_allowed(device), "{device:?}");
    }
}

#[test]
fn a_listing_that_cannot_run_lists_nothing() {
    let absent = PathBuf::from("/nonexistent/speech");
    assert!(list_gpus(&absent, &None).is_empty());
    assert_eq!(device_rows(&absent, &None), None);
    // The stand-in refuses every subcommand but `serve`: an exit with an error.
    let fake = PathBuf::from(env!("CARGO_BIN_EXE_fake-speech"));
    assert!(list_gpus(&fake, &None).is_empty());
    assert_eq!(device_rows(&fake, &None), None);
}

#[test]
fn a_bundle_is_admitted_only_with_its_pinned_executable() {
    let folder = std::env::temp_dir().join(format!("vrct-speech-bundle-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&folder);
    assert_eq!(bundled_binary(&folder).err(), Some(codes::BUNDLE));
    std::fs::create_dir_all(&folder).unwrap();
    let binary = folder.join(vrct_speech_server::bundle::EXECUTABLE);
    std::fs::write(&binary, b"not the pinned executable").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    for meta in [
        json!({"schema": 1, "version": "0.10.0", "variant": "linux-x64-vulkan"}), // another file's hash
        json!({"schema": 1, "version": "0.9.0", "variant": "linux-x64-vulkan"}),
        json!({"schema": true, "version": "0.10.0", "variant": "linux-x64-vulkan"}),
        json!({"schema": 1, "version": "0.10.0", "variant": "unknown"}),
        json!([]),
    ] {
        std::fs::write(folder.join("bundle.json"), meta.to_string()).unwrap();
        assert_eq!(bundled_binary(&folder).err(), Some(codes::BUNDLE), "{meta}");
    }
    let _ = std::fs::remove_dir_all(&folder);
}

/// With VRCT_SPEECHCPP_BUNDLE naming a real `build/speechcpp`, the pinned executable is
/// admitted and lists this PC's devices. Skipped without it: the bundle is 30 MB.
#[test]
fn the_real_bundle_is_admitted_and_lists_devices() {
    let Some(bundle) = std::env::var_os("VRCT_SPEECHCPP_BUNDLE") else { return };
    let binary = bundled_binary(&PathBuf::from(bundle)).unwrap();
    let rows = device_rows(&binary, &None).unwrap();
    assert!(rows.iter().any(|row| row["kind"] == "cpu"), "{rows:?}");
    let named = resolve_device("auto", Some(&rows));
    assert!(device_allowed(&named));
}
