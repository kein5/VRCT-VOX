//! Optional bounded warm requests to an owned Irodori GPU server.
//!
//! Generated audio is discarded here: no router, user text, microphone or queue. This
//! trades idle power for latency; it is never enabled by default.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crate::http::{request, Body, Cancel};
use crate::warmup::speech_request;
use crate::{codes, Code};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Health {
    /// `warming`, `ready`, `failed` or `stopped`.
    pub state: &'static str,
    pub completed: u64,
    pub error_code: Option<Code>,
}

struct Shared {
    health: Health,
    token: Option<Arc<Cancel>>,
    thread: Option<JoinHandle<()>>,
    started: bool,
    finished: bool,
}

struct Inner {
    port: u16,
    interval: Duration,
    stop: AtomicBool,
    shared: Mutex<Shared>,
    changed: Condvar,
}

pub struct LowLatencyStandby {
    inner: Arc<Inner>,
}

impl LowLatencyStandby {
    pub fn new(port: u16) -> LowLatencyStandby {
        LowLatencyStandby::with_interval(port, Duration::from_millis(100))
    }

    pub fn with_interval(port: u16, interval: Duration) -> LowLatencyStandby {
        let health = Health { state: "warming", completed: 0, error_code: None };
        let shared = Shared { health, token: None, thread: None, started: false, finished: false };
        LowLatencyStandby {
            inner: Arc::new(Inner {
                port,
                interval,
                stop: AtomicBool::new(false),
                shared: Mutex::new(shared),
                changed: Condvar::new(),
            }),
        }
    }

    pub fn health(&self) -> Health {
        self.inner.shared.lock().unwrap().health.clone()
    }

    pub fn start(&self) -> Result<(), Code> {
        let mut shared = self.inner.shared.lock().unwrap();
        if shared.started || self.inner.stop.load(Ordering::SeqCst) {
            return Err("low_latency_single_use");
        }
        shared.started = true;
        let inner = self.inner.clone();
        let thread = std::thread::Builder::new().name("vrct-vox-standby".into()).spawn(move || inner.run());
        match thread {
            Ok(thread) => shared.thread = Some(thread),
            Err(_) => {
                shared.finished = true;
                shared.health = Health { state: "failed", completed: 0, error_code: Some(codes::LOW_LATENCY_FAILED) };
            }
        }
        Ok(())
    }

    /// Stop the requests. False when the thread did not end within `timeout`.
    pub fn close(&self, timeout: Duration) -> bool {
        self.inner.stop.store(true, Ordering::SeqCst);
        let mut shared = self.inner.shared.lock().unwrap();
        if let Some(token) = shared.token.clone() {
            token.cancel();
        }
        self.inner.changed.notify_all();
        if !shared.started {
            return true;
        }
        let deadline = Instant::now() + timeout;
        while !shared.finished {
            let Some(remaining) = deadline.checked_duration_since(Instant::now()) else { return false };
            shared = self.inner.changed.wait_timeout(shared, remaining).unwrap().0;
        }
        if let Some(thread) = shared.thread.take() {
            drop(shared);
            let _ = thread.join();
        }
        true
    }
}

impl Inner {
    fn run(&self) {
        let body = speech_request("あ。", Some(0));
        let mut failed = false;
        while !self.stop.load(Ordering::SeqCst) {
            let token = Arc::new(Cancel::new());
            {
                let mut shared = self.shared.lock().unwrap();
                if self.stop.load(Ordering::SeqCst) {
                    break;
                }
                shared.token = Some(token.clone());
            }
            // Bound the entire discard operation, including a stalled body.
            let deadline = Instant::now() + Duration::from_secs(2);
            let spoken = request(
                self.port,
                "POST",
                "/v1/audio/speech",
                Some(("application/json", &body)),
                Body::Discard,
                deadline,
                Some(&token),
            )
            .is_ok_and(|response| response.status == 200);
            let mut shared = self.shared.lock().unwrap();
            shared.token = None;
            if !spoken || token.is_set() {
                failed = !self.stop.load(Ordering::SeqCst);
                break;
            }
            shared.health.state = "ready";
            shared.health.completed += 1;
            let (_shared, _) =
                self.changed.wait_timeout_while(shared, self.interval, |_| !self.stop.load(Ordering::SeqCst)).unwrap();
        }
        let mut shared = self.shared.lock().unwrap();
        shared.token = None;
        if self.stop.load(Ordering::SeqCst) {
            shared.health.state = "stopped";
            shared.health.error_code = None;
        } else if failed {
            shared.health.state = "failed";
            shared.health.error_code = Some(codes::LOW_LATENCY_FAILED);
        }
        shared.finished = true;
        self.changed.notify_all();
    }
}
