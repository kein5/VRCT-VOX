//! One owned speech.cpp server: started once, watched until it ends.

use std::io::Read;
use std::path::PathBuf;
use std::process::Child;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{sync_channel, Receiver, RecvTimeoutError};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::{JoinHandle, ThreadId};
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::bundle::bundled_binary;
use crate::child;
use crate::devices::{command, device_rows, resolve_device, Environment};
use crate::http::{request, Body, Cancel};
use crate::settings::{Profile, StartOptions};
use crate::standby::{self, LowLatencyStandby};
use crate::warmup::warm_up;
use crate::{codes, Code};

/// How long a server may take from its start to its first answer.
pub const START_TIMEOUT: Duration = Duration::from_secs(120);
/// What a warm-up leaves of the start timeout, so it cannot be what fails the start.
const WARM_UP_MARGIN: Duration = Duration::from_secs(2);
const LINE_LIMIT: usize = 65536;
/// The loader reports a missing import as this NTSTATUS. Only vulkan-1.dll can be
/// missing: the executable's other imports are all part of Windows.
#[cfg(windows)]
const DLL_NOT_FOUND: u32 = 0xC000_0135;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum State {
    Stopped,
    Preparing,
    Ready,
    Stopping,
    Failed,
}

impl State {
    pub fn name(self) -> &'static str {
        match self {
            State::Stopped => "stopped",
            State::Preparing => "preparing",
            State::Ready => "ready",
            State::Stopping => "stopping",
            State::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Health {
    pub state: State,
    /// `http://127.0.0.1:<port>` while the server is ready.
    pub base_url: Option<String>,
    pub error_code: Option<Code>,
    pub low_latency: Option<standby::Health>,
}

impl Health {
    pub(crate) fn stopped() -> Health {
        Health { state: State::Stopped, base_url: None, error_code: None, low_latency: None }
    }
}

/// Where the executable comes from.
#[derive(Clone, Debug)]
pub enum Binary {
    /// The app's `build/speechcpp` folder, checked against the pinned hashes at each start.
    Bundled(PathBuf),
    /// A given executable, unchecked and never asked for its devices. For tests.
    Fixed(PathBuf),
}

#[derive(Clone, Debug)]
pub struct Launch {
    pub binary: Binary,
    pub environment: Environment,
    pub start_timeout: Duration,
}

impl Launch {
    pub fn bundled(bundle: impl Into<PathBuf>) -> Launch {
        Launch { binary: Binary::Bundled(bundle.into()), environment: None, start_timeout: START_TIMEOUT }
    }

    pub fn fixed(binary: impl Into<PathBuf>) -> Launch {
        Launch { binary: Binary::Fixed(binary.into()), environment: None, start_timeout: START_TIMEOUT }
    }
}

type Hook<T> = Option<Box<dyn Fn(T) + Send + Sync>>;

/// What the owner of a server is told. None of these receive server output.
#[derive(Default)]
pub struct Hooks {
    /// The server ended, for any reason. Called once, after its child is gone.
    pub on_end: Hook<Profile>,
    /// The server failed with this code. For the usage events.
    pub on_failure: Hook<Code>,
    /// A speech (not recognition) server listens on this port with this process id; it
    /// is told again with None when the server ends. For the audio listener monitor.
    pub on_listener: Hook<Option<(u16, u32)>>,
    /// "auto" or "gpu" was resolved to this device for this start.
    pub on_device: Hook<String>,
}

struct Done {
    finished: Mutex<bool>,
    changed: Condvar,
}

impl Done {
    fn new() -> Arc<Done> {
        Arc::new(Done { finished: Mutex::new(false), changed: Condvar::new() })
    }

    fn finish(&self) {
        *self.finished.lock().unwrap() = true;
        self.changed.notify_all();
    }

    fn wait(&self, timeout: Duration) -> bool {
        let finished = self.finished.lock().unwrap();
        *self.changed.wait_timeout_while(finished, timeout, |finished| !*finished).unwrap().0
    }
}

struct Shared {
    health: Health,
    options: StartOptions,
    started: bool,
    thread: Option<(ThreadId, JoinHandle<()>)>,
    child: Option<Arc<Mutex<Child>>>,
    pid: Option<u32>,
    standby: Option<Arc<LowLatencyStandby>>,
    warm_token: Option<Arc<Cancel>>,
    cleanup_ok: bool,
}

struct Inner {
    profile: Profile,
    launch: Launch,
    hooks: Hooks,
    stop: AtomicBool,
    shared: Mutex<Shared>,
    done: Arc<Done>,
}

/// A server that is started at most once. A restart is a new `SpeechServer`.
pub struct SpeechServer {
    inner: Arc<Inner>,
}

impl SpeechServer {
    pub fn new(profile: Profile, options: StartOptions, launch: Launch, hooks: Hooks) -> SpeechServer {
        let shared = Shared {
            health: Health::stopped(),
            options,
            started: false,
            thread: None,
            child: None,
            pid: None,
            standby: None,
            warm_token: None,
            cleanup_ok: true,
        };
        SpeechServer {
            inner: Arc::new(Inner {
                profile,
                launch,
                hooks,
                stop: AtomicBool::new(false),
                shared: Mutex::new(shared),
                done: Done::new(),
            }),
        }
    }

    pub fn profile(&self) -> Profile {
        self.inner.profile
    }

    pub fn health(&self) -> Health {
        self.inner.health()
    }

    /// The process id of the server, once it was launched.
    pub fn pid(&self) -> Option<u32> {
        self.inner.shared.lock().unwrap().pid
    }

    /// The device this start uses, after "auto" and "gpu" were resolved.
    pub fn device(&self) -> String {
        self.inner.shared.lock().unwrap().options.device.clone()
    }

    pub fn start(&self) -> Result<(), Code> {
        let mut shared = self.inner.shared.lock().unwrap();
        if shared.started || self.inner.stop.load(Ordering::SeqCst) {
            return Err(codes::SINGLE_USE);
        }
        shared.started = true;
        shared.health.state = State::Preparing;
        let inner = self.inner.clone();
        let name = format!("vrct-speech-{}", self.inner.profile.name());
        match std::thread::Builder::new().name(name).spawn(move || inner.run()) {
            Ok(thread) => shared.thread = Some((thread.thread().id(), thread)),
            Err(_) => {
                shared.health.state = State::Failed;
                shared.health.error_code = Some(codes::LAUNCH_FAILED);
                self.inner.done.finish();
            }
        }
        Ok(())
    }

    /// Ask the server to end. It returns at once; `close` waits for the end.
    pub fn stop(&self) {
        let token = {
            let mut shared = self.inner.shared.lock().unwrap();
            self.inner.stop.store(true, Ordering::SeqCst);
            shared.health.base_url = None;
            if matches!(shared.health.state, State::Preparing | State::Ready) {
                shared.health.state = State::Stopping;
            }
            shared.warm_token.clone()
        };
        if let Some(token) = token {
            token.cancel();
        }
    }

    /// Stop and wait. True when the server's child is known to be gone.
    pub fn close(&self, timeout: Duration) -> bool {
        self.stop();
        let (started, own_thread) = {
            let shared = self.inner.shared.lock().unwrap();
            let own = shared.thread.as_ref().is_some_and(|(id, _)| *id == std::thread::current().id());
            (shared.started, own)
        };
        let finished = !started || (!own_thread && self.inner.done.wait(timeout));
        if finished {
            let thread = self.inner.shared.lock().unwrap().thread.take();
            if let Some((_, thread)) = thread {
                let _ = thread.join();
            }
        }
        finished && self.inner.shared.lock().unwrap().cleanup_ok
    }
}

/// `\x1b[...m` colour codes removed.
fn strip_ansi(line: &[u8]) -> Vec<u8> {
    let mut clean = Vec::with_capacity(line.len());
    let mut at = 0;
    while at < line.len() {
        if line[at] == 0x1b && line.get(at + 1) == Some(&b'[') {
            let mut end = at + 2;
            while end < line.len() && (line[end].is_ascii_digit() || line[end] == b';') {
                end += 1;
            }
            if line.get(end) == Some(&b'm') {
                at = end + 1;
                continue;
            }
        }
        clean.push(line[at]);
        at += 1;
    }
    clean
}

/// speech.cpp prints a failure as "speech: <category>: ..." or "speech: <category> (<option>): ...".
/// These two categories have a next step of their own for the user.
fn engine_failure(line: &[u8]) -> Option<Code> {
    [(&b"speech: out_of_memory"[..], codes::OUT_OF_MEMORY), (&b"speech: device"[..], codes::DEVICE_FAILED)]
        .into_iter()
        .find_map(|(prefix, code)| {
            let rest = line.strip_prefix(prefix)?;
            (rest.starts_with(b":") || rest.starts_with(b" (")).then_some(code)
        })
}

/// The port in "API at http://127.0.0.1:<port>/v1", which ends the line or precedes a ";".
fn ready_port(line: &[u8]) -> Option<Result<u16, Code>> {
    const MARK: &[u8] = b"API at http://127.0.0.1:";
    (0..line.len().saturating_sub(MARK.len())).find_map(|at| {
        let rest = line[at..].strip_prefix(MARK)?;
        let digits = rest.iter().take(5).take_while(|byte| byte.is_ascii_digit()).count();
        let after = rest[digits..].strip_prefix(b"/v1")?;
        if digits == 0 || !(after.is_empty() || after[0] == b';') {
            return None;
        }
        let port: u32 = std::str::from_utf8(&rest[..digits]).ok()?.parse().ok()?;
        Some(u16::try_from(port).ok().filter(|port| *port != 0).ok_or(codes::PROTOCOL))
    })
}

/// Numeric loopback only, with a total request deadline even for slow headers.
fn get_json(port: u16, path: &str, deadline: Instant) -> Result<Value, Code> {
    let remaining = deadline
        .checked_duration_since(Instant::now())
        .filter(|left| !left.is_zero())
        .ok_or(codes::START_TIMEOUT)?
        .min(Duration::from_millis(500));
    let response = request(port, "GET", path, None, Body::Keep(65536), Instant::now() + remaining, None)
        .map_err(|_| codes::READINESS)?;
    if response.status != 200 {
        return Err(codes::READINESS);
    }
    serde_json::from_slice(&response.body).map_err(|_| codes::READINESS)
}

impl Inner {
    fn health(&self) -> Health {
        let shared = self.shared.lock().unwrap();
        let mut health = shared.health.clone();
        health.low_latency = shared.standby.as_ref().map(|standby| standby.health());
        health
    }

    fn stopping(&self) -> bool {
        self.stop.load(Ordering::SeqCst)
    }

    fn arguments(&self, options: &StartOptions) -> Vec<String> {
        let mut args = vec!["serve".to_owned(), options.model.clone()];
        for model in [&options.vad_model, &options.diarization_model] {
            if !model.is_empty() {
                args.push(model.clone());
            }
        }
        args.extend(["--host", "127.0.0.1", "--port", "0", "--device"].map(str::to_owned));
        args.push(options.device.clone());
        if !options.voice_file.is_empty() {
            args.extend(["--add-voice".to_owned(), format!("custom={}", options.voice_file)]);
        }
        args
    }

    /// The server answered on `port`: check what it serves, then warm it up off this thread.
    fn ready(
        self: &Arc<Self>,
        port: u16,
        deadline: Instant,
        warm: &mut Option<(JoinHandle<()>, Arc<Done>)>,
    ) -> Result<(), Code> {
        if get_json(port, "/health", deadline)? != serde_json::json!({"status": "ok"}) {
            return Err(codes::READINESS);
        }
        if self.stopping() {
            return Ok(());
        }
        let models = get_json(port, "/v1/models", deadline)?;
        let rows = models.get("data").and_then(Value::as_array).ok_or(codes::MODEL_TASKS)?;
        let mut tasks = rows
            .iter()
            .map(|row| row.get("speech")?.get("task")?.as_str())
            .collect::<Option<Vec<_>>>()
            .ok_or(codes::MODEL_TASKS)?;
        let (low_latency, diarization) = {
            let shared = self.shared.lock().unwrap();
            (shared.options.low_latency, !shared.options.diarization_model.is_empty())
        };
        let mut expected =
            if self.profile == Profile::Asr { vec!["recognition", "detection"] } else { vec!["synthesis"] };
        // A file in the diarization field that is another kind of model fails here.
        if self.profile == Profile::Asr && diarization {
            expected.push("diarization");
        }
        tasks.sort_unstable();
        expected.sort_unstable();
        if tasks != expected {
            return Err(codes::MODEL_TASKS);
        }
        if self.profile != Profile::Asr {
            if let (Some(hook), Some(pid)) = (&self.hooks.on_listener, self.shared.lock().unwrap().pid) {
                hook(Some((port, pid)));
            }
        }
        if low_latency {
            let speech = &rows[0]["speech"];
            let device = speech.get("device").and_then(Value::as_str).unwrap_or("CPU");
            if self.profile != Profile::Japanese
                || speech.get("architecture").and_then(Value::as_str) != Some("irodori-tts")
                || device.eq_ignore_ascii_case("cpu")
            {
                return Err(codes::LOW_LATENCY_REQUIRES_GPU_IRODORI);
            }
            self.shared.lock().unwrap().standby = Some(Arc::new(LowLatencyStandby::new(port)));
        }
        // This thread has to keep reading the child's output and watching for its exit
        // while the warm-up runs, and that can take many seconds.
        let (inner, rows, done) = (self.clone(), rows.clone(), Done::new());
        let finished = done.clone();
        let name = format!("vrct-speech-warm-{}", self.profile.name());
        let thread = std::thread::Builder::new().name(name).spawn(move || {
            inner.finish_start(port, &rows, deadline);
            finished.finish();
        });
        *warm = Some((thread.map_err(|_| codes::LAUNCH_FAILED)?, done));
        Ok(())
    }

    fn finish_start(&self, port: u16, models: &[Value], deadline: Instant) {
        let token = Arc::new(Cancel::new());
        {
            let mut shared = self.shared.lock().unwrap();
            shared.warm_token = Some(token.clone());
            if self.stopping() {
                token.cancel();
            }
        }
        let limit = deadline.checked_duration_since(Instant::now()).and_then(|left| left.checked_sub(WARM_UP_MARGIN));
        // Only the first real request pays for a warm-up that failed.
        warm_up(self.profile, port, models, &token, limit);
        let standby = self.shared.lock().unwrap().standby.clone();
        if let Some(standby) = standby.filter(|_| !self.stopping()) {
            let _ = standby.start();
        }
        let mut shared = self.shared.lock().unwrap();
        shared.warm_token = None;
        let alive = shared.child.as_ref().is_some_and(|child| matches!(child.lock().unwrap().try_wait(), Ok(None)));
        if !self.stopping() && alive {
            shared.health.state = State::Ready;
            shared.health.base_url = Some(format!("http://127.0.0.1:{port}"));
        }
    }

    fn watch(
        self: &Arc<Self>,
        warm: &mut Option<(JoinHandle<()>, Arc<Done>)>,
        lines: &mut Option<Receiver<Vec<u8>>>,
    ) -> Result<(), Code> {
        let deadline = Instant::now() + self.launch.start_timeout;
        let binary = match &self.launch.binary {
            Binary::Fixed(binary) => binary.clone(),
            Binary::Bundled(bundle) => bundled_binary(bundle)?,
        };
        if self.stopping() {
            return Ok(());
        }
        // Asked here, at each start: an external GPU may have been plugged in or out.
        if matches!(self.launch.binary, Binary::Bundled(_)) {
            let asked = self.shared.lock().unwrap().options.device.clone();
            let rows = if matches!(asked.as_str(), "auto" | "gpu") {
                device_rows(&binary, &self.launch.environment)
            } else {
                None
            };
            let device = resolve_device(&asked, rows.as_deref());
            if device != asked {
                self.shared.lock().unwrap().options.device = device.clone();
                if let Some(hook) = &self.hooks.on_device {
                    hook(device);
                }
            }
        }
        if self.stopping() {
            return Ok(());
        }
        let options = self.shared.lock().unwrap().options.clone();
        let mut launch = command(&binary, &self.launch.environment);
        launch.args(self.arguments(&options));
        let mut owned = child::spawn(launch).map_err(|_| codes::LAUNCH_FAILED)?;
        let stderr = owned.child.stderr.take();
        let child = Arc::new(Mutex::new(owned.child));
        {
            let mut shared = self.shared.lock().unwrap();
            shared.pid = Some(child.lock().unwrap().id());
            shared.child = Some(child.clone());
        }
        // The job (Windows) lives as long as this function's caller keeps the child.
        #[cfg(windows)]
        let _job = owned.job;

        // The pipe is read on its own thread: a read of it cannot be bounded in time.
        let (sender, receiver) = sync_channel::<Vec<u8>>(64);
        let reader = std::thread::Builder::new().name("vrct-speech-output".into()).spawn(move || {
            let Some(mut stderr) = stderr else { return };
            let mut block = [0u8; 8192];
            while let Ok(read) = stderr.read(&mut block) {
                if read == 0 || sender.send(block[..read].to_vec()).is_err() {
                    break;
                }
            }
        });
        if reader.is_err() {
            return Err(codes::LAUNCH_FAILED);
        }
        let receiver = lines.insert(receiver);

        let mut exit_error = codes::EXITED;
        let mut pending: Vec<u8> = Vec::new();
        let mut open = true;
        while !self.stopping() {
            let status = child.lock().unwrap().try_wait().map_err(|_| codes::LAUNCH_FAILED)?;
            let exited = status.is_some();
            let is_ready = self.shared.lock().unwrap().health.state == State::Ready;
            if !exited && !is_ready && Instant::now() >= deadline {
                return Err(codes::START_TIMEOUT);
            }
            #[cfg(windows)]
            if status.is_some_and(|status| status.code() == Some(DLL_NOT_FOUND as i32)) {
                exit_error = codes::VULKAN_MISSING;
            }
            if exited {
                // A fast failure can exit before the first read. Take a bounded amount
                // of what it wrote, including its final partial line.
                let until = Instant::now() + Duration::from_millis(500);
                while open && pending.len() <= LINE_LIMIT {
                    match receiver.recv_timeout(until.saturating_duration_since(Instant::now())) {
                        Ok(data) => pending.extend(data),
                        Err(_) => break,
                    }
                }
                if !pending.is_empty() && !pending.ends_with(b"\n") {
                    pending.push(b'\n');
                }
            } else if open {
                match receiver.recv_timeout(Duration::from_millis(50)) {
                    Ok(data) => pending.extend(data),
                    Err(RecvTimeoutError::Timeout) => continue,
                    Err(RecvTimeoutError::Disconnected) => open = false,
                }
            } else {
                // The server closed its error stream and still runs: only its exit is left to see.
                std::thread::sleep(Duration::from_millis(50));
                continue;
            }
            while let Some(end) = pending.iter().position(|byte| *byte == b'\n') {
                let mut line: Vec<u8> = pending.drain(..=end).collect();
                line.pop();
                if line.len() > LINE_LIMIT {
                    return Err(codes::PROTOCOL);
                }
                let mut line = strip_ansi(&line);
                while line.last() == Some(&b'\r') {
                    line.pop();
                }
                // Only the fixed engine's error category is mapped. The line itself, which
                // can contain local model paths or input, goes nowhere.
                if let Some(code) = engine_failure(&line) {
                    if exit_error != codes::OUT_OF_MEMORY {
                        exit_error = code;
                    }
                }
                if exited || self.shared.lock().unwrap().health.state == State::Ready || warm.is_some() {
                    continue;
                }
                if let Some(port) = ready_port(&line) {
                    self.ready(port?, deadline, warm)?;
                }
            }
            if pending.len() > LINE_LIMIT {
                return Err(codes::PROTOCOL);
            }
            if exited {
                return Err(exit_error);
            }
        }
        Ok(())
    }

    fn run(self: Arc<Self>) {
        let mut warm = None;
        let mut lines = None;
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.watch(&mut warm, &mut lines)));
        let mut failure = match outcome {
            Ok(result) => result.err(),
            Err(_) => Some(codes::LAUNCH_FAILED),
        };

        // End the warm-up first: it holds a request to the child that is about to go.
        let token = self.shared.lock().unwrap().warm_token.clone();
        if let Some(token) = token {
            token.cancel();
        }
        if let Some((thread, done)) = warm.take() {
            if done.wait(Duration::from_secs(1)) {
                let _ = thread.join();
            }
        }
        let (standby, child, listened) = {
            let shared = self.shared.lock().unwrap();
            (shared.standby.clone(), shared.child.clone(), self.profile != Profile::Asr && shared.pid.is_some())
        };
        if listened {
            if let Some(hook) = &self.hooks.on_listener {
                hook(None);
            }
        }
        let mut cleanup_ok = standby.is_none_or(|standby| standby.close(Duration::from_secs(1)));
        if let Some(child) = child {
            cleanup_ok &= child::end(&mut child.lock().unwrap());
        }
        drop(lines);
        {
            let mut shared = self.shared.lock().unwrap();
            shared.cleanup_ok = cleanup_ok;
            if !cleanup_ok {
                failure = Some(codes::CLEANUP_UNCONFIRMED);
            } else if self.stopping() {
                failure = None;
            }
            shared.health.state = if failure.is_some() { State::Failed } else { State::Stopped };
            shared.health.base_url = None;
            shared.health.error_code = failure;
        }
        if let (Some(code), Some(hook)) = (failure, &self.hooks.on_failure) {
            let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| hook(code)));
        }
        if let Some(hook) = &self.hooks.on_end {
            if std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| hook(self.profile))).is_err() {
                let mut shared = self.shared.lock().unwrap();
                shared.health.state = State::Failed;
                shared.health.error_code = Some(codes::NOTIFICATION_FAILED);
            }
        }
        self.done.finish();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_ready_line_gives_its_port_and_nothing_else_does() {
        assert_eq!(ready_port(b"    API at http://127.0.0.1:8080/v1; Ctrl-C stops the server"), Some(Ok(8080)));
        assert_eq!(ready_port(b"API at http://127.0.0.1:65535/v1"), Some(Ok(65535)));
        assert_eq!(ready_port(b"API at http://127.0.0.1:0/v1"), Some(Err(codes::PROTOCOL)));
        assert_eq!(ready_port(b"API at http://127.0.0.1:70000/v1"), Some(Err(codes::PROTOCOL)));
        assert_eq!(ready_port(b"API at http://127.0.0.1:8080/v1/models"), None);
        assert_eq!(ready_port(b"API at http://127.0.0.1:808080/v1"), None);
        assert_eq!(ready_port(b"API at http://192.168.0.2:8080/v1"), None);
        assert_eq!(ready_port(b""), None);
    }

    #[test]
    fn only_the_two_engine_categories_are_mapped() {
        assert_eq!(engine_failure(b"speech: out_of_memory: cannot allocate"), Some(codes::OUT_OF_MEMORY));
        assert_eq!(engine_failure(b"speech: device (--device): no device"), Some(codes::DEVICE_FAILED));
        assert_eq!(engine_failure(b"speech: device: failed"), Some(codes::DEVICE_FAILED));
        assert_eq!(engine_failure(b"speech: devices: x"), None);
        assert_eq!(engine_failure(b"note speech: device: x"), None);
        assert_eq!(engine_failure(b"speech: model: x"), None);
    }

    #[test]
    fn colour_codes_are_removed() {
        assert_eq!(strip_ansi(b"\x1b[31mspeech: device: x\x1b[0m"), b"speech: device: x");
        assert_eq!(strip_ansi(b"\x1b[1;31ma\x1b[K"), b"a\x1b[K");
    }
}
