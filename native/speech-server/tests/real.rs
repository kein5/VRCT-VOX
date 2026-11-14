//! The real bundled speech.cpp with a real model, for a PC that has both. Skipped unless
//! VRCT_SPEECHCPP_BUNDLE names a `build/speechcpp` folder and VRCT_SPEECH_MODEL a speech
//! (synthesis) model file. VRCT_SPEECH_DEVICE picks the device, "cpu" unless given.

use std::time::{Duration, Instant};

use serde_json::json;
use vrct_speech_server::server::{Hooks, Launch, SpeechServer, State};
use vrct_speech_server::settings::{start_options, Profile};

#[test]
fn the_real_server_starts_answers_and_stops() {
    let (Some(bundle), Some(model)) =
        (std::env::var_os("VRCT_SPEECHCPP_BUNDLE"), std::env::var("VRCT_SPEECH_MODEL").ok())
    else {
        return;
    };
    let device = std::env::var("VRCT_SPEECH_DEVICE").unwrap_or_else(|_| "cpu".into());
    let settings = json!({"profiles": {"multilingual": {"model": model, "device": device}}});
    let options = start_options(&settings, Profile::Multilingual).unwrap();
    let server = SpeechServer::new(Profile::Multilingual, options, Launch::bundled(bundle), Hooks::default());
    server.start().unwrap();
    let deadline = Instant::now() + Duration::from_secs(120);
    while !matches!(server.health().state, State::Ready | State::Failed) {
        assert!(Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(50));
    }
    let health = server.health();
    eprintln!("state {} code {:?} device {}", health.state.name(), health.error_code, server.device());
    assert_eq!(health.state, State::Ready, "{:?}", health.error_code);
    let pid = server.pid().unwrap();
    assert!(server.close(Duration::from_secs(5)));
    assert!(!std::path::Path::new(&format!("/proc/{pid}")).exists());
    assert_eq!(server.health().state, State::Stopped);
}
