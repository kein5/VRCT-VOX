//! Stands in for the speech.cpp executable in the tests: `fake-speech serve MODEL ...`.
//! The stem of MODEL's file name picks what it does. No model, GPU or audio.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::Path;
use std::time::Duration;

fn stem(path: Option<&String>) -> String {
    path.and_then(|path| Path::new(path).file_stem())
        .map(|stem| stem.to_string_lossy().into_owned())
        .unwrap_or_default()
}

fn respond(stream: &mut TcpStream, status: &str, kind: &str, extra: &str, body: &[u8]) {
    let head = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {kind}\r\n{extra}Content-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    let _ = stream.write_all(head.as_bytes());
    let _ = stream.write_all(body);
}

fn handle(mut stream: TcpStream, mode: &str, diarization: bool) {
    let mut request = Vec::new();
    let mut block = [0u8; 65536];
    let (head_end, length) = loop {
        let Ok(read) = stream.read(&mut block) else { return };
        if read == 0 {
            return;
        }
        request.extend_from_slice(&block[..read]);
        if let Some(end) = request.windows(4).position(|four| four == b"\r\n\r\n") {
            let head = String::from_utf8_lossy(&request[..end]).to_ascii_lowercase();
            let length = head
                .lines()
                .find_map(|line| line.strip_prefix("content-length:"))
                .and_then(|value| value.trim().parse::<usize>().ok())
                .unwrap_or(0);
            break (end, length);
        }
    };
    while request.len() < head_end + 4 + length {
        let Ok(read) = stream.read(&mut block) else { return };
        if read == 0 {
            return;
        }
        request.extend_from_slice(&block[..read]);
    }
    let line = String::from_utf8_lossy(&request[..head_end]).lines().next().unwrap_or("").to_owned();
    let body = &request[head_end + 4..];
    if line.starts_with("GET ") {
        if mode == "badhealth" {
            return respond(&mut stream, "500 Internal Server Error", "text/plain", "", b"");
        }
        if line.starts_with("GET /health ") {
            return respond(&mut stream, "200 OK", "application/json", "", br#"{"status":"ok"}"#);
        }
        let mut tasks = if mode == "asr" { vec!["recognition", "detection"] } else { vec!["synthesis"] };
        if mode == "asr" && diarization {
            tasks.push("diarization");
        }
        if mode == "wrong" {
            tasks.clear();
        }
        let architecture = if mode.starts_with("irodori") { "irodori-tts" } else { "other" };
        let device = if mode == "irodori_cpu" { "CPU" } else { "Vulkan0" };
        let rows: Vec<String> = tasks
            .iter()
            .map(|task| {
                format!(r#"{{"id":"{task}","speech":{{"task":"{task}","architecture":"{architecture}","device":"{device}","options":[{{"name":"seed","type":"int"}}]}}}}"#)
            })
            .collect();
        return respond(
            &mut stream,
            "200 OK",
            "application/json",
            "",
            format!(r#"{{"data":[{}]}}"#, rows.join(",")).as_bytes(),
        );
    }
    if line.starts_with("POST /v1/audio/transcriptions ") {
        // The warm-up sends a WAVE file in a multipart body.
        let sent = body.windows(4).any(|four| four == b"RIFF");
        return respond(
            &mut stream,
            if sent { "200 OK" } else { "400 Bad Request" },
            "application/json",
            "",
            br#"{"text":""}"#,
        );
    }
    if line.starts_with("POST /v1/audio/speech ") {
        let text = String::from_utf8_lossy(body);
        // The standby's one-syllable request names seed 0; no request names a voice.
        let valid = text.contains(r#""voice":"none""#) && (!text.contains("あ。") || text.contains(r#""seed":0"#));
        let pcm = [1u8, 0].repeat(480);
        return respond(
            &mut stream,
            if valid { "200 OK" } else { "400 Bad Request" },
            "audio/pcm",
            "X-Sample-Rate: 48000\r\n",
            &pcm,
        );
    }
    respond(&mut stream, "404 Not Found", "text/plain", "", b"");
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) != Some("serve") {
        std::process::exit(2);
    }
    let mode = stem(args.get(2));
    let diarization = stem(args.get(4)) == "diarization";
    let fail = |message: &str, newline: bool| -> ! {
        eprint!("{message}{}", if newline { "\n" } else { "" });
        std::process::exit(1);
    };
    match mode.as_str() {
        "crash" => std::process::exit(1),
        "oom" => fail("speech: out_of_memory: cannot allocate /private/model.gguf on Vulkan0", true),
        "oom_ansi" => {
            fail("\x1b[31mspeech: out_of_memory: cannot allocate /private/model.gguf on Vulkan0\x1b[0m", true)
        }
        "oom_unterminated" => fail("speech: out_of_memory: cannot allocate /private/model.gguf on Vulkan0", false),
        "device" => fail("speech: device: the device Vulkan0 failed to compute a graph: /private/model.gguf", true),
        "device_option" => fail("speech: device (--device): no device is named /private/Vulkan9", true),
        "wait" => {
            std::thread::sleep(Duration::from_secs(30));
            return;
        }
        "overflow" => {
            eprint!("{}", "x".repeat(70000));
            std::thread::sleep(Duration::from_secs(30));
            return;
        }
        _ => {}
    }
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
    let port = listener.local_addr().expect("address").port();
    eprintln!("    API at http://127.0.0.1:{port}/v1; Ctrl-C stops the server");
    for stream in listener.incoming().flatten() {
        let mode = mode.clone();
        std::thread::spawn(move || handle(stream, &mode, diarization));
    }
}
