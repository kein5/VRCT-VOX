//! Which device a server is told to use, from what the bundled speech.cpp lists.

use std::ffi::OsString;
use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::settings::is_named_gpu;

/// A GPU in the text `speech devices` prints.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Gpu {
    pub name: String,
    /// `gpu` for a separate GPU, `igpu` for an integrated one.
    pub kind: String,
    pub label: String,
}

/// The line `Vulkan0    gpu   <label>, 8.0 GB, 7.5 GB free`.
fn parse_line(line: &str) -> Option<Gpu> {
    let digits = line.strip_prefix("Vulkan")?.bytes().take(2).take_while(u8::is_ascii_digit).count();
    let (name, rest) = line.split_at(6 + digits);
    if digits == 0 || !rest.starts_with(char::is_whitespace) {
        return None;
    }
    let rest = rest.trim_start();
    let kind = ["igpu", "gpu"].into_iter().find(|kind| rest.starts_with(kind))?;
    let rest = &rest[kind.len()..];
    if !rest.starts_with(char::is_whitespace) {
        return None;
    }
    let rest = rest.trim_start();
    // The label ends at the first ", <number> GB,".
    let label_end = rest.char_indices().filter(|(at, c)| *c == ',' && *at > 0).map(|(at, _)| at).find(|at| {
        let after = &rest[at + 1..];
        let number = after.trim_start();
        let size = number.bytes().take_while(|byte| byte.is_ascii_digit() || *byte == b'.').count();
        number.len() < after.len() && size > 0 && number[size..].starts_with(" GB,")
    })?;
    Some(Gpu { name: name.to_owned(), kind: kind.to_owned(), label: rest[..label_end].to_owned() })
}

/// The GPUs in `speech devices` output; the CPU is a choice of its own.
pub fn parse_devices(text: &str) -> Vec<Gpu> {
    text.lines().filter_map(parse_line).collect()
}

/// Vulkan devices that are not a GPU of this PC to compute on: a software rasterizer, and
/// Microsoft's mapping of Vulkan onto Direct3D 12, on which models load and the first
/// compute fails.
fn not_a_compute_gpu(description: &str) -> bool {
    let text = description.to_ascii_lowercase();
    ["llvmpipe", "lavapipe", "swiftshader", "direct3d 12", "direct3d12", "microsoft basic"]
        .iter()
        .any(|name| text.contains(name))
}

fn kind(row: &Value) -> Option<&str> {
    row.get("kind")?.as_str().filter(|kind| matches!(*kind, "gpu" | "igpu"))
}

/// The Vulkan device "auto" and "gpu" mean, from `speech devices --json` rows, or None.
///
/// speech.cpp takes the first GPU it lists, and lists an integrated GPU first on a PC with
/// both. A separate GPU is faster for every vendor, so it comes first, then the one with
/// the most memory. AMD, Intel and NVIDIA are treated alike.
pub fn preferred_gpu(rows: &[Value]) -> Option<String> {
    let mut best: Option<((bool, u64), &str)> = None;
    for row in rows {
        let (Some(kind), Some(name)) = (kind(row), row.get("name").and_then(Value::as_str)) else { continue };
        let description = match row.get("description") {
            None => String::new(),
            Some(Value::String(text)) => text.clone(),
            Some(other) => other.to_string(),
        };
        if !is_named_gpu(name) || not_a_compute_gpu(&description) {
            continue;
        }
        let rank = (kind == "gpu", row.get("memory_total").and_then(Value::as_u64).unwrap_or(0));
        // The first of equals, as speech.cpp lists them.
        if best.is_none_or(|(held, _)| rank > held) {
            best = Some((rank, name));
        }
    }
    best.map(|(_, name)| name.to_owned())
}

/// What to pass to `--device`: a chosen Vulkan device for "auto" and "gpu", else unchanged.
///
/// "auto" stays "auto" when the PC shows no GPU, so speech.cpp uses the CPU as before. When
/// it shows only devices that cannot compute, "auto" means the CPU: speech.cpp would take
/// one of them and fail on the first request. "gpu" stays "gpu" without a usable GPU, so
/// that choice still fails with the device notice. `rows` is None when listing failed.
pub fn resolve_device(device: &str, rows: Option<&[Value]>) -> String {
    let (true, Some(rows)) = (matches!(device, "auto" | "gpu"), rows) else { return device.to_owned() };
    if let Some(chosen) = preferred_gpu(rows) {
        return chosen;
    }
    let shown = rows.iter().any(|row| kind(row).is_some());
    if device == "auto" && shown {
        "cpu".to_owned()
    } else {
        device.to_owned()
    }
}

/// What a child of this app is started with besides `NO_COLOR`: None inherits this
/// process's environment, Some replaces it (a packaged app passes the one it had
/// before its own loader changed the library paths).
pub type Environment = Option<Vec<(OsString, OsString)>>;

pub(crate) fn command(binary: &Path, environment: &Environment) -> Command {
    let mut command = Command::new(binary);
    if let Some(environment) = environment {
        command.env_clear().envs(environment.iter().map(|(key, value)| (key, value)));
    }
    command.env("NO_COLOR", "1").stdin(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(windows_sys::Win32::System::Threading::CREATE_NO_WINDOW);
    }
    command
}

/// The output of `speech devices [--json]`, both streams, or None on any failure.
fn run_devices(binary: &Path, environment: &Environment, json: bool) -> Option<(Vec<u8>, Vec<u8>)> {
    let mut command = command(binary, environment);
    command.arg("devices").stdout(Stdio::piped()).stderr(Stdio::piped());
    if json {
        command.arg("--json");
    }
    let mut child = command.spawn().ok()?;
    let readers: Vec<_> = [
        child.stdout.take().map(|s| Box::new(s) as Box<dyn Read + Send>),
        child.stderr.take().map(|s| Box::new(s) as Box<dyn Read + Send>),
    ]
    .into_iter()
    .map(|stream| {
        std::thread::spawn(move || {
            let mut data = Vec::new();
            if let Some(stream) = stream {
                let _ = stream.take(1024 * 1024).read_to_end(&mut data);
            }
            data
        })
    })
    .collect();
    let deadline = Instant::now() + Duration::from_secs(15);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(10)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
        }
    };
    let mut output = readers.into_iter().map(|reader| reader.join().unwrap_or_default());
    let (stdout, stderr) = (output.next()?, output.next()?);
    status.filter(|status| status.success()).map(|_| (stdout, stderr))
}

/// The GPUs a server can be told to use, by the names the bundled speech.cpp prints.
pub fn list_gpus(binary: &Path, environment: &Environment) -> Vec<Gpu> {
    let Some((mut text, stderr)) = run_devices(binary, environment, false) else { return Vec::new() };
    text.extend(stderr);
    parse_devices(&String::from_utf8_lossy(&text))
}

/// The rows of `speech devices --json`, or None when they cannot be read.
pub fn device_rows(binary: &Path, environment: &Environment) -> Option<Vec<Value>> {
    let (stdout, _) = run_devices(binary, environment, true)?;
    let value: Value = serde_json::from_slice(&stdout).ok()?;
    Some(value.get("devices").and_then(Value::as_array).cloned().unwrap_or_default())
}
