fn main() {
    println!("cargo:rerun-if-env-changed=VRCT_LINUX_BUNDLE");
    // Guard stale sidecar resources too: a direct `cargo tauri build` must
    // not package the restricted upstream OCR model in a fork release.
    check_fork_resources();
    tauri_build::build()
}

fn check_fork_resources() {
    println!("cargo:rerun-if-changed=bin/_internal");
    println!("cargo:rerun-if-changed=../tools/check_voice_distribution.py");
    println!("cargo:rerun-if-changed=../tools/distribution_policy.py");
    println!("cargo:rerun-if-env-changed=VRCT_BUILD_PYTHON");
    if !std::path::Path::new("bin/_internal").exists() {
        return;
    }
    // Use the same policy for direct Tauri builds, ZIPs and PyInstaller hooks.
    let python = std::env::var("VRCT_BUILD_PYTHON")
        .unwrap_or_else(|_| if cfg!(windows) { "python" } else { "python3" }.into());
    let status = std::process::Command::new(python)
        .args(["../tools/check_voice_distribution.py", "bin/_internal"])
        .status()
        .expect("Python 3 is required for distribution inspection");
    assert!(status.success(), "Fork resource inspection failed; rebuild the sidecar without excluded assets");
}
