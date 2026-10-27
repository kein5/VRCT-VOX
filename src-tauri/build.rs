fn main() {
    // Guard stale sidecar resources too: a direct `cargo tauri build` must
    // not package the restricted upstream OCR model in a fork release.
    check_fork_resources(std::path::Path::new("bin/_internal"));
    tauri_build::build()
}

fn check_fork_resources(path: &std::path::Path) {
    println!("cargo:rerun-if-changed={}", path.display());
    if !path.exists() {
        return;
    }
    if path.is_dir() {
        for entry in std::fs::read_dir(path).expect("cannot inspect sidecar resources") {
            check_fork_resources(&entry.expect("cannot inspect resource").path());
        }
    } else if path.file_name().is_some_and(|name| {
        name.to_string_lossy().eq_ignore_ascii_case("chatbox_yolox_tiny.onnx")
    }) {
        panic!("Restricted OCR model in fork package: {}. Rebuild the sidecar without it.", path.display());
    }
}
