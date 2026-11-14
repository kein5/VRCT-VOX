//! Owned fake HTTP children exercise real process lifetime; no models or GPU.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use vrct_speech_server::server::{Hooks, Launch, SpeechServer, State};
use vrct_speech_server::settings::{normalize_settings, start_options, Profile, StartOptions};
use vrct_speech_server::{codes, SpeechServers};

const FAKE: &str = env!("CARGO_BIN_EXE_fake-speech");

struct Folder(PathBuf);

impl Folder {
    fn new() -> Folder {
        static NEXT: AtomicU32 = AtomicU32::new(0);
        let name = format!("vrct-speech-server-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::SeqCst));
        let path = std::env::temp_dir().join(name);
        std::fs::create_dir_all(&path).unwrap();
        Folder(path.canonicalize().unwrap())
    }

    fn gguf(&self, name: &str) -> String {
        let path = self.0.join(format!("{name}.gguf"));
        std::fs::write(&path, b"GGUF\0\0\0\0\0\0\0\0").unwrap();
        path.to_str().unwrap().to_owned()
    }
}

impl Drop for Folder {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn options(folder: &Folder, name: &str, profile: Profile, diarization: Option<&str>) -> StartOptions {
    let mut row = json!({"model": folder.gguf(name)});
    if profile == Profile::Asr {
        row["vad_model"] = folder.gguf("vad").into();
    }
    if let Some(diarization) = diarization {
        row["diarization_model"] = folder.gguf(diarization).into();
    }
    start_options(&json!({"profiles": {profile.name(): row}}), profile).unwrap()
}

fn launch(timeout: Duration) -> Launch {
    let mut launch = Launch::fixed(FAKE);
    launch.start_timeout = timeout;
    launch
}

fn server(profile: Profile, options: StartOptions) -> SpeechServer {
    SpeechServer::new(profile, options, launch(Duration::from_secs(3)), Hooks::default())
}

fn wait_for(what: impl Fn() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(4);
    while !what() {
        assert!(Instant::now() < deadline, "the condition did not come true");
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn settled(server: &SpeechServer) -> State {
    wait_for(|| matches!(server.health().state, State::Ready | State::Failed));
    server.health().state
}

#[cfg(target_os = "linux")]
fn gone(pid: u32) -> bool {
    // A reaped child has no entry; a zombie would still have one.
    !Path::new(&format!("/proc/{pid}")).exists()
}

#[cfg(not(target_os = "linux"))]
fn gone(_pid: u32) -> bool {
    true
}

const SECOND: Duration = Duration::from_secs(3);

#[test]
fn choices_persist_without_recording_process_intent() {
    let default = normalize_settings(&json!({})).unwrap();
    let row = json!({"model": "", "vad_model": "", "diarization_model": "", "voice_file": "", "device": "auto", "low_latency": false});
    assert_eq!(
        default.to_json(),
        json!({"version": 1, "profiles": {"japanese": row, "multilingual": row, "asr": row}})
    );
    let mut chosen = default.to_json();
    chosen["profiles"]["asr"]["model"] = "/absent/user-choice.gguf".into();
    chosen["profiles"]["asr"]["diarization_model"] = "/absent/who-speaks.gguf".into();
    assert_eq!(normalize_settings(&chosen).unwrap().to_json(), chosen);
    // Settings saved before the diarization model existed load with none.
    let older = json!({"profiles": {"asr": {"model": "/m.gguf", "vad_model": "/v.gguf", "voice_file": "", "device": "gpu", "low_latency": false}}});
    assert_eq!(normalize_settings(&older).unwrap().profile(Profile::Asr).diarization_model, "");
    assert_eq!(
        normalize_settings(&json!({"profiles": {"asr": {"device": "Vulkan12"}}})).unwrap().profile(Profile::Asr).device,
        "Vulkan12"
    );
}

#[test]
fn invalid_settings_are_rejected() {
    let cases = [
        Value::Null,
        json!({"version": true}),
        json!({"version": 1.0}),
        json!({"version": 2}),
        json!({"active": true}),
        json!({"profiles": {"unknown": {}}}),
        json!({"profiles": {"japanese": {"device": "cuda:0"}}}),
        json!({"profiles": {"japanese": {"device": "Vulkan123"}}}),
        json!({"profiles": {"japanese": {"model": "bad\npath"}}}),
        json!({"profiles": {"japanese": {"model": "x".repeat(4097)}}}),
        json!({"profiles": {"japanese": {"vad_model": "wrong.gguf"}}}),
        json!({"profiles": {"japanese": {"diarization_model": "wrong.gguf"}}}),
        json!({"profiles": {"multilingual": {"diarization_model": "wrong.gguf"}}}),
        json!({"profiles": {"multilingual": {"low_latency": true}}}),
        json!({"profiles": {"japanese": {"low_latency": 1}}}),
        json!({"profiles": {"asr": {"diarization_model": 1}}}),
        json!({"profiles": {"asr": {"voice_file": "wrong.gguf"}}}),
        json!({"profiles": {"asr": {"started": true}}}),
    ];
    for case in cases {
        assert_eq!(normalize_settings(&case).err(), Some(codes::SETTINGS_INVALID), "{case}");
    }
}

#[test]
fn a_start_requires_local_gguf_files() {
    let folder = Folder::new();
    let bad = folder.0.join("bad.gguf");
    std::fs::write(&bad, b"BAD!").unwrap();
    let asr = folder.gguf("asr");
    let cases = [
        (Profile::Japanese, json!({})),
        (Profile::Japanese, json!({"model": "qwen3-tts-0.6b"})),
        (Profile::Japanese, json!({"model": bad.to_str().unwrap()})),
        (Profile::Asr, json!({"model": asr})),
        (
            Profile::Asr,
            json!({"model": asr, "vad_model": asr, "diarization_model": folder.0.join("absent.gguf").to_str().unwrap()}),
        ),
    ];
    for (profile, row) in cases {
        let settings = json!({"profiles": {profile.name(): row}});
        assert_eq!(start_options(&settings, profile).err(), Some(codes::MODEL_INVALID), "{settings}");
    }
    assert_eq!(options(&folder, "asr", Profile::Asr, None).diarization_model, "");
    let named = options(&folder, "asr", Profile::Asr, Some("diarization"));
    assert_eq!(Path::new(&named.diarization_model), folder.0.join("diarization.gguf"));
}

#[test]
fn an_asr_server_loads_the_diarization_model_it_is_given() {
    let folder = Folder::new();
    for (name, state, code) in
        [("diarization", State::Ready, None), ("another", State::Failed, Some(codes::MODEL_TASKS))]
    {
        let server = server(Profile::Asr, options(&folder, "asr", Profile::Asr, Some(name)));
        server.start().unwrap();
        assert_eq!(settled(&server), state);
        assert_eq!(server.health().error_code, code);
        assert!(server.close(SECOND));
    }
}

#[test]
fn a_server_becomes_ready_then_stops_and_reaps_its_child() {
    let folder = Folder::new();
    for (profile, model) in [(Profile::Japanese, "tts"), (Profile::Multilingual, "tts"), (Profile::Asr, "asr")] {
        let ended = Arc::new(Mutex::new(Vec::new()));
        let listeners = Arc::new(Mutex::new(Vec::new()));
        let (told, heard) = (ended.clone(), listeners.clone());
        let hooks = Hooks {
            on_end: Some(Box::new(move |profile| told.lock().unwrap().push(profile))),
            on_listener: Some(Box::new(move |listener| heard.lock().unwrap().push(listener))),
            ..Hooks::default()
        };
        let server = SpeechServer::new(profile, options(&folder, model, profile, None), launch(SECOND), hooks);
        assert_eq!(server.health().state, State::Stopped);
        server.start().unwrap();
        assert_eq!(settled(&server), State::Ready, "{:?}", server.health());
        let url = server.health().base_url.unwrap();
        assert!(url.starts_with("http://127.0.0.1:"));
        let pid = server.pid().unwrap();
        assert!(!gone(pid));
        server.stop();
        assert_eq!(server.health().base_url, None);
        assert!(server.close(SECOND));
        assert!(gone(pid));
        assert_eq!(server.health().state, State::Stopped);
        assert_eq!(*ended.lock().unwrap(), [profile]);
        // Only a speech server has a listener to watch, and its end is told too.
        let port: u16 = url.rsplit(':').next().unwrap().parse().unwrap();
        let expected = if profile == Profile::Asr { vec![] } else { vec![Some((port, pid)), None] };
        assert_eq!(*listeners.lock().unwrap(), expected);
        assert_eq!(server.start().err(), Some(codes::SINGLE_USE));
    }
}

#[test]
fn a_stop_during_load_cannot_later_become_ready() {
    let folder = Folder::new();
    let server = server(Profile::Japanese, options(&folder, "wait", Profile::Japanese, None));
    server.start().unwrap();
    wait_for(|| server.pid().is_some());
    let pid = server.pid().unwrap();
    let began = Instant::now();
    server.stop();
    assert!(server.close(SECOND));
    assert!(began.elapsed() < SECOND);
    assert!(gone(pid));
    assert_eq!(server.health().state, State::Stopped);
    assert_eq!(server.start().err(), Some(codes::SINGLE_USE));
}

#[test]
fn the_opt_in_standby_is_owned_and_ends_with_the_server() {
    let folder = Folder::new();
    let mut opts = options(&folder, "irodori", Profile::Japanese, None);
    opts.low_latency = true;
    let server = server(Profile::Japanese, opts);
    server.start().unwrap();
    wait_for(|| server.health().low_latency.is_some_and(|standby| standby.completed >= 2));
    assert_eq!(server.health().state, State::Ready);
    assert!(server.close(SECOND));
    assert_eq!(server.health().low_latency.unwrap().state, "stopped");
}

#[test]
fn the_opt_in_standby_rejects_an_unsupported_or_cpu_model() {
    let folder = Folder::new();
    for name in ["tts", "irodori_cpu"] {
        let mut opts = options(&folder, name, Profile::Japanese, None);
        opts.low_latency = true;
        let server = server(Profile::Japanese, opts);
        server.start().unwrap();
        assert_eq!(settled(&server), State::Failed);
        assert_eq!(server.health().error_code, Some(codes::LOW_LATENCY_REQUIRES_GPU_IRODORI));
        assert_eq!(server.health().low_latency, None);
        assert!(server.close(SECOND));
    }
}

#[test]
fn a_failed_start_is_bounded_and_does_not_publish_an_endpoint() {
    let folder = Folder::new();
    let cases = [
        ("wrong", codes::MODEL_TASKS),
        ("overflow", codes::PROTOCOL),
        ("crash", codes::EXITED),
        ("badhealth", codes::READINESS),
        ("wait", codes::START_TIMEOUT),
    ];
    for (mode, code) in cases {
        let failures = Arc::new(Mutex::new(Vec::new()));
        let told = failures.clone();
        let hooks =
            Hooks { on_failure: Some(Box::new(move |code| told.lock().unwrap().push(code))), ..Hooks::default() };
        let timeout = if mode == "wait" { Duration::from_millis(400) } else { SECOND };
        let server = SpeechServer::new(
            Profile::Japanese,
            options(&folder, mode, Profile::Japanese, None),
            launch(timeout),
            hooks,
        );
        server.start().unwrap();
        assert_eq!(settled(&server), State::Failed);
        assert_eq!(server.health().error_code, Some(code), "{mode}");
        assert_eq!(server.health().base_url, None);
        assert!(server.close(SECOND));
        assert!(server.pid().is_none_or(gone));
        assert_eq!(*failures.lock().unwrap(), [code]);
    }
}

#[test]
fn a_missing_executable_is_a_launch_failure_and_a_missing_bundle_is_named() {
    let folder = Folder::new();
    let opts = options(&folder, "tts", Profile::Japanese, None);
    let absent =
        SpeechServer::new(Profile::Japanese, opts.clone(), Launch::fixed(folder.0.join("absent")), Hooks::default());
    absent.start().unwrap();
    assert_eq!(settled(&absent), State::Failed);
    assert_eq!(absent.health().error_code, Some(codes::LAUNCH_FAILED));
    let unbundled =
        SpeechServer::new(Profile::Japanese, opts, Launch::bundled(folder.0.join("speechcpp")), Hooks::default());
    unbundled.start().unwrap();
    assert_eq!(settled(&unbundled), State::Failed);
    assert_eq!(unbundled.health().error_code, Some(codes::BUNDLE));
}

#[cfg(unix)]
#[test]
fn the_death_of_a_ready_server_invalidates_its_endpoint() {
    let folder = Folder::new();
    let ended = Arc::new(Mutex::new(Vec::new()));
    let told = ended.clone();
    let hooks = Hooks { on_end: Some(Box::new(move |profile| told.lock().unwrap().push(profile))), ..Hooks::default() };
    let server =
        SpeechServer::new(Profile::Japanese, options(&folder, "tts", Profile::Japanese, None), launch(SECOND), hooks);
    server.start().unwrap();
    assert_eq!(settled(&server), State::Ready);
    let killed = std::process::Command::new("kill").args(["-9", &server.pid().unwrap().to_string()]).status().unwrap();
    assert!(killed.success());
    wait_for(|| server.health().state == State::Failed);
    assert_eq!(server.health().error_code, Some(codes::EXITED));
    assert_eq!(server.health().base_url, None);
    wait_for(|| *ended.lock().unwrap() == [Profile::Japanese]);
    assert!(server.close(SECOND));
}

#[test]
fn an_engine_failure_is_named_without_what_the_engine_printed() {
    let folder = Folder::new();
    let cases = [
        ("device", codes::DEVICE_FAILED),
        ("device_option", codes::DEVICE_FAILED),
        ("oom", codes::OUT_OF_MEMORY),
        ("oom_ansi", codes::OUT_OF_MEMORY),
        ("oom_unterminated", codes::OUT_OF_MEMORY),
    ];
    for (mode, code) in cases {
        let server = server(Profile::Asr, options(&folder, mode, Profile::Asr, None));
        server.start().unwrap();
        assert_eq!(settled(&server), State::Failed);
        let health = server.health();
        assert_eq!((health.base_url.clone(), health.error_code), (None, Some(code)), "{mode}");
        // The public state contains no model path or unfiltered output.
        assert!(!format!("{health:?}").contains("/private/"));
        assert!(server.close(SECOND));
    }
}

#[test]
fn the_hub_rejects_a_stale_start_and_never_reuses_a_stopped_endpoint() {
    let folder = Folder::new();
    let ends = Arc::new(Mutex::new(Vec::new()));
    let told = ends.clone();
    let hub = SpeechServers::new(
        launch(SECOND),
        Some(Box::new(move |profile, run| told.lock().unwrap().push((profile, run)))),
    );
    let opts = options(&folder, "tts", Profile::Japanese, None);
    let generation = |hub: &SpeechServers| hub.state()[0].1.generation;
    let state = |hub: &SpeechServers| hub.state()[0].1.health.state;

    let before = generation(&hub);
    assert!(hub.stop(Profile::Japanese, None, None));
    assert_eq!(hub.start(Profile::Japanese, opts.clone(), before).err(), Some(codes::STALE_START));
    assert_eq!(hub.binding(Profile::Japanese).err(), Some(codes::NOT_READY));
    hub.start(Profile::Japanese, opts.clone(), generation(&hub)).unwrap();
    wait_for(|| state(&hub) == State::Ready);
    let first = hub.binding(Profile::Japanese).unwrap();
    assert!(first.starts_with("http://127.0.0.1:"));
    assert_eq!(hub.start(Profile::Japanese, opts.clone(), generation(&hub)).err(), Some(codes::BUSY));

    // A Stop that names an older generation is refused; the current one stops the run it names.
    let running = generation(&hub);
    let run = hub.current_run(Profile::Japanese);
    assert!(!hub.stop(Profile::Japanese, Some(running - 1), None));
    let stopped = Mutex::new(None);
    assert!(hub.stop(
        Profile::Japanese,
        Some(running),
        Some(&|profile, run| *stopped.lock().unwrap() = Some((profile, run)))
    ));
    assert_eq!(*stopped.lock().unwrap(), Some((Profile::Japanese, run)));
    assert_eq!(hub.binding(Profile::Japanese).err(), Some(codes::NOT_READY));
    wait_for(|| state(&hub) == State::Stopped);

    // A restart is a new server on a new run.
    wait_for(|| hub.start(Profile::Japanese, opts.clone(), generation(&hub)).is_ok());
    wait_for(|| state(&hub) == State::Ready);
    assert_ne!(hub.current_run(Profile::Japanese), run);
    assert!(hub.close(SECOND));
    assert_eq!(hub.start(Profile::Japanese, opts, generation(&hub)).err(), Some(codes::CLOSED));
    assert_eq!(hub.binding(Profile::Japanese).err(), Some(codes::NOT_READY));
    // A server the user stopped tells its end once; a closed hub's server ends without a second notice.
    assert_eq!(ends.lock().unwrap().iter().filter(|(_, ended)| Some(*ended) == run).count(), 1);
}
