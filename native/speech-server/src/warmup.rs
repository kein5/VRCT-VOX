//! One discarded request after an owned GPU server comes up.
//!
//! With an empty driver cache, a server's first real sentence or caption waits for the
//! driver to build its kernels. Doing that here keeps the first one from being lost. No
//! microphone, router or queue is involved, and the result is thrown away. A warm-up that
//! fails only means the first real request is slow, so it never stops the server.

use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::http::{request, Body, Cancel};
use crate::settings::Profile;

/// A sentence of this length is what builds the kernels: on an RTX 3060 Ti with an empty
/// cache a one-syllable request took 0.08 s and the next sentence still waited 8 s.
pub const TEXT: &str = "こんにちは、今日はよろしくお願いします。";
/// Likewise 2 s of noise warmed nothing, and after 6 s real speech took 0.08 s.
pub const NOISE_SECONDS: usize = 6;
const RATE: usize = 16000;

/// Six seconds of fixed quiet noise as a 16 kHz mono 16-bit WAVE file.
pub fn noise_wav() -> Vec<u8> {
    let samples = NOISE_SECONDS * RATE;
    let mut wav = Vec::with_capacity(44 + samples * 2);
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&((36 + samples * 2) as u32).to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16u32.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes()); // PCM
    wav.extend_from_slice(&1u16.to_le_bytes()); // mono
    wav.extend_from_slice(&(RATE as u32).to_le_bytes());
    wav.extend_from_slice(&((RATE * 2) as u32).to_le_bytes());
    wav.extend_from_slice(&2u16.to_le_bytes());
    wav.extend_from_slice(&16u16.to_le_bytes());
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&((samples * 2) as u32).to_le_bytes());
    // A fixed generator: the sum of twelve uniform values is close to a normal one.
    let mut state: u64 = 0x9E37_79B9_7F4A_7C15;
    let mut uniform = move || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        (state >> 11) as f64 / (1u64 << 53) as f64
    };
    for _ in 0..samples {
        let normal: f64 = (0..12).map(|_| uniform()).sum::<f64>() - 6.0;
        wav.extend_from_slice(&((normal * 1800.0) as i16).to_le_bytes());
    }
    wav
}

/// The id of the model doing `task`, if it runs somewhere that has kernels to build.
fn on_gpu(models: &[Value], task: &str) -> Option<String> {
    models.iter().find_map(|row| {
        let speech = row.get("speech")?;
        let device = speech.get("device").and_then(Value::as_str).unwrap_or("CPU");
        (speech.get("task")?.as_str()? == task && !device.eq_ignore_ascii_case("cpu"))
            .then(|| row.get("id")?.as_str().map(str::to_owned))?
    })
}

/// The request that speaks `text` and returns raw PCM, which the callers throw away.
pub(crate) fn speech_request(text: &str, seed: Option<u64>) -> Vec<u8> {
    let mut body = json!({"input": text, "voice": "none", "language": "ja", "response_format": "pcm"});
    if let Some(seed) = seed {
        body["seed"] = seed.into();
    }
    body.to_string().into_bytes()
}

fn speak(port: u16, cancel: &Cancel, deadline: Instant) -> bool {
    let body = speech_request(TEXT, None);
    request(port, "POST", "/v1/audio/speech", Some(("application/json", &body)), Body::Discard, deadline, Some(cancel))
        .is_ok_and(|response| response.status == 200)
}

fn transcribe(port: u16, model: &str, cancel: &Cancel, deadline: Instant) -> bool {
    let boundary = "vrct-vox-warm-up-7d0c1f5e9a3b";
    let mut body = format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n\
         --{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"noise.wav\"\r\n\
         Content-Type: audio/wav\r\n\r\n"
    )
    .into_bytes();
    body.extend(noise_wav());
    body.extend(format!("\r\n--{boundary}--\r\n").into_bytes());
    let kind = format!("multipart/form-data; boundary={boundary}");
    request(port, "POST", "/v1/audio/transcriptions", Some((&kind, &body)), Body::Discard, deadline, Some(cancel))
        .is_ok_and(|response| response.status == 200)
}

/// Whether a warm-up ran. Other profiles have no voice known to be accepted.
pub fn warm_up(profile: Profile, port: u16, models: &[Value], cancel: &Cancel, limit: Option<Duration>) -> bool {
    let Some(limit) = limit.filter(|limit| !limit.is_zero()) else { return false };
    if cancel.is_set() {
        return false;
    }
    let deadline = Instant::now() + limit;
    match profile {
        Profile::Japanese if on_gpu(models, "synthesis").is_some() => speak(port, cancel, deadline),
        Profile::Asr => match on_gpu(models, "recognition") {
            Some(model) if !model.contains(['\r', '\n']) => transcribe(port, &model, cancel, deadline),
            _ => false,
        },
        _ => false,
    }
}
