//! Sharing one window with chat reading through the XDG ScreenCast portal.
//!
//! The backend reads an X11/XWayland window by its name. A native Wayland
//! window (VRChat inside gamescope, or with Wine's Wayland driver) can only be
//! read when the user picks it in the desktop's own dialog; its frames then
//! arrive over PipeWire. This module asks the portal, hands the PipeWire
//! connection to a small helper (`native/screen-capture`) and ends both when
//! asked, when the window goes away or when the app exits. The helper writes
//! the newest frame to `<private directory>/screen-frame`, where the backend's
//! chat reading finds it (`src-python/models/ocr/ocr_capture_portal.py`).
//!
//! Nothing here runs until the main window calls `screencast_start`, which the
//! page only does when the user presses the button for it.
use std::collections::HashMap;
use std::future::poll_fn;
use std::io::{BufRead, BufReader};
use std::os::fd::OwnedFd;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::process::{Child, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::task::Poll;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State, WebviewWindow};
use zbus::export::futures_core::Stream;
use zbus::zvariant::{OwnedObjectPath, OwnedValue, Value};
use zbus::{Connection, MatchRule, MessageStream, Proxy};

use crate::portal_shortcuts::worker::wait_until;
use crate::portal_shortcuts::{ensure_desktop_file, failure, next, portal_owner_lost, APP_ID, BACKENDS, DESKTOP, DESTINATION};

const INTERFACE: &str = "org.freedesktop.portal.ScreenCast";
const HELPER: &str = "vrct-screen-capture";
/// The backend reads this file in the directory `vr_panel_surface` prepared.
const FRAME_NAME: &str = "screen-frame";
const SOURCE_WINDOW: u32 = 2;
const CURSOR_HIDDEN: u32 = 1;
/// The desktop keeps the permission until the user revokes it there.
const PERSIST_UNTIL_REVOKED: u32 = 2;
const SETUP_TIMEOUT: Duration = Duration::from_secs(15);
/// The user chooses a window in the desktop's dialog.
const DIALOG_TIMEOUT: Duration = Duration::from_secs(180);
const STREAM_TIMEOUT: Duration = Duration::from_secs(10);
/// Chat reading looks at the window about once a second; more frames are only copied and dropped.
const FRAME_INTERVAL_MS: u32 = 250;
const TOKEN_LIMIT: usize = 512;

/// What `screencast_start` answers: the token that restores this choice next time, if the desktop gave one.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Started {
    restore_token: Option<String>,
}

#[derive(Clone, Serialize)]
pub struct Support {
    supported: bool,
    active: bool,
}

#[derive(Clone, Serialize)]
struct Ended {
    reason: &'static str,
}

struct Running {
    stop: Arc<AtomicBool>,
    thread: std::thread::JoinHandle<()>,
}

#[derive(Default)]
pub struct Screencast(Mutex<Option<Running>>);

impl Screencast {
    /// Asks the current sharing to end. Returns at once; `take` waits for it.
    fn cancel(&self) {
        if let Ok(current) = self.0.lock() {
            if let Some(running) = current.as_ref() {
                running.stop.store(true, Ordering::Release);
            }
        }
    }

    fn take(&self) -> Option<Running> {
        self.0.lock().ok()?.take()
    }

    fn active(&self) -> bool {
        self.0.lock().is_ok_and(|current| current.as_ref().is_some_and(|running| !running.thread.is_finished()))
    }
}

/// One start or stop at a time, so a new sharing never overlaps the helper of the previous one.
static SERIAL: tauri::async_runtime::Mutex<()> = tauri::async_runtime::Mutex::const_new(());

/// A saved token is sent back only when it looks like one; anything else means "ask the user".
fn usable_token(token: Option<&str>) -> Option<&str> {
    token.filter(|token| !token.is_empty() && token.len() <= TOKEN_LIMIT && !token.chars().any(char::is_control))
}

/// The options of `SelectSources`: one window, no pointer in the picture, and a permission the desktop remembers.
/// `version` and `cursor_modes` are what this desktop's portal says it supports.
fn select_options<'a>(handle_token: &'a str, version: u32, cursor_modes: u32, restore_token: Option<&'a str>) -> HashMap<&'static str, Value<'a>> {
    let mut options = HashMap::from([
        ("handle_token", Value::from(handle_token)),
        ("types", Value::from(SOURCE_WINDOW)),
        ("multiple", Value::from(false)),
    ]);
    if cursor_modes & CURSOR_HIDDEN != 0 {
        options.insert("cursor_mode", Value::from(CURSOR_HIDDEN));
    }
    // Restoring a choice exists from version 4 on; an older portal rejects the unknown options.
    if version >= 4 {
        options.insert("persist_mode", Value::from(PERSIST_UNTIL_REVOKED));
        if let Some(token) = usable_token(restore_token) {
            options.insert("restore_token", Value::from(token));
        }
    }
    options
}

fn text(results: &HashMap<String, OwnedValue>, key: &str) -> Option<String> {
    results.get(key).and_then(|value| value.try_clone().ok()).and_then(|value| String::try_from(value).ok())
}

/// The session a `CreateSession` response names.
fn session_handle(results: &HashMap<String, OwnedValue>) -> Result<OwnedObjectPath, String> {
    let handle = match results.get("session_handle").map(|value| &**value) {
        Some(Value::Str(path)) => path.as_str().to_owned(),
        Some(Value::ObjectPath(path)) => path.as_str().to_owned(),
        _ => return Err("portal_request_failed".into()),
    };
    OwnedObjectPath::try_from(handle).map_err(|_| "portal_request_failed".into())
}

/// The PipeWire node of the shared window and the token for next time, from a `Start` response.
fn started(results: &HashMap<String, OwnedValue>) -> Result<(u32, Started), String> {
    let streams = results.get("streams")
        .and_then(|value| value.try_clone().ok())
        .and_then(|value| Vec::<(u32, HashMap<String, OwnedValue>)>::try_from(value).ok())
        .ok_or("portal_request_failed")?;
    // One window was asked for (`multiple` is false).
    let (node, _) = streams.first().ok_or("portal_request_failed")?;
    let restore_token = text(results, "restore_token").filter(|token| usable_token(Some(token)).is_some());
    Ok((*node, Started { restore_token }))
}

/// Where the helper may be: next to the packaged backend (the archive keeps it beside the app, the
/// AppImage under `usr/lib/vrct-vox` while the app is in `usr/bin`), or in the checkout a
/// development build came from.
fn helper_candidates(executable: &Path, checkout: Option<&Path>) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(directory) = executable.parent() {
        candidates.push(directory.join("_internal/build").join(HELPER));
        if let Some(prefix) = directory.parent() {
            candidates.push(prefix.join("lib/vrct-vox/_internal/build").join(HELPER));
        }
    }
    if let Some(checkout) = checkout {
        candidates.push(checkout.join("build").join(HELPER));
    }
    candidates
}

fn helper_path() -> Option<PathBuf> {
    let executable = std::env::current_exe().ok()?;
    let checkout = if cfg!(debug_assertions) { Path::new(env!("CARGO_MANIFEST_DIR")).parent() } else { None };
    helper_candidates(&executable, checkout).into_iter().find(|path| path.is_file())
}

/// What `LD_LIBRARY_PATH` the helper gets. Inside the AppImage the app itself runs with its bundled
/// libraries first (`packaging/appimage/AppRun` records what the host had); the helper has to load
/// the host's PipeWire, like the backend does. `None`: not in the AppImage, leave it alone.
/// `Some(None)`: the host had none. `Some(Some(path))`: the host's value.
fn host_library_path(recorded: Option<&str>, value: Option<&str>) -> Option<Option<String>> {
    recorded.map(|recorded| (recorded == "x").then(|| value.unwrap_or_default().to_owned()))
}

fn frame_path() -> Option<PathBuf> {
    let directory = std::env::var_os(crate::vr_panel_surface::DIRECTORY_ENV).map(PathBuf::from)?;
    directory.is_dir().then(|| directory.join(FRAME_NAME))
}

#[derive(Debug, PartialEq)]
enum HelperLine {
    Streaming,
    Failed(String),
}

/// What one line of the helper's stderr means. PipeWire may print lines of its own there.
fn helper_line(line: &str) -> Option<HelperLine> {
    let line = line.trim_end();
    if line == "streaming" {
        return Some(HelperLine::Streaming);
    }
    let reason = line.strip_prefix("screen_capture_")?;
    let plain = !reason.is_empty() && reason.len() <= 48 && reason.bytes().all(|byte| byte.is_ascii_lowercase() || byte == b'_');
    plain.then(|| HelperLine::Failed(reason.to_owned()))
}

/// Why a sharing that was running is over, as the page is told. `None` when the app itself ended it.
/// "ended": the window was closed or the user stopped sharing from the desktop. "failed": something broke.
fn end_reason(stop_requested: bool, session_closed: bool, helper_failure: Option<&str>) -> Option<&'static str> {
    if stop_requested {
        None
    } else if session_closed || helper_failure == Some("stream_ended") {
        Some("ended")
    } else {
        Some("failed")
    }
}

struct Helper {
    child: Child,
    /// The helper stops when this end of its stdout pipe closes.
    lifeline: Option<ChildStdout>,
    lines: mpsc::Receiver<HelperLine>,
    frame: PathBuf,
}

impl Helper {
    fn start(program: &Path, remote: OwnedFd, node: u32, frame: &Path) -> Result<Self, String> {
        let mut command = Command::new(program);
        command.arg(std::process::id().to_string())
            .arg(node.to_string())
            .arg(frame)
            .arg(FRAME_INTERVAL_MS.to_string())
            // The portal's PipeWire connection becomes the helper's stdin; nothing else is inherited by number.
            .stdin(Stdio::from(remote))
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let recorded = std::env::var("VRCT_APPIMAGE_HOST_LD_LIBRARY_PATH_SET").ok();
        let host = std::env::var("VRCT_APPIMAGE_HOST_LD_LIBRARY_PATH").ok();
        match host_library_path(recorded.as_deref(), host.as_deref()) {
            Some(Some(path)) => { command.env("LD_LIBRARY_PATH", path); }
            Some(None) => { command.env_remove("LD_LIBRARY_PATH"); }
            None => {}
        }
        let mut child = command.spawn().map_err(|_| "screencast_helper_failed")?;
        let lifeline = child.stdout.take();
        let (sender, lines) = mpsc::channel();
        if let Some(stderr) = child.stderr.take() {
            let reader = std::thread::Builder::new().name("vrct-screen-capture-log".into()).spawn(move || {
                for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    let Some(parsed) = helper_line(&line) else { continue };
                    if let HelperLine::Failed(reason) = &parsed {
                        crate::startup_log(&format!("Window sharing helper stopped: {reason}"));
                    }
                    if sender.send(parsed).is_err() {
                        break;
                    }
                }
            });
            if reader.is_err() {
                let _ = child.kill();
                let _ = child.wait();
                return Err("screencast_helper_failed".into());
            }
        }
        Ok(Self { child, lifeline, lines, frame: frame.to_owned() })
    }

    /// Waits until frames can flow.
    fn wait_streaming(&mut self, check: impl Fn() -> Result<(), String>) -> Result<(), String> {
        let deadline = Instant::now() + STREAM_TIMEOUT;
        loop {
            check()?;
            match self.lines.recv_timeout(Duration::from_millis(50)) {
                Ok(HelperLine::Streaming) => return Ok(()),
                Ok(HelperLine::Failed(_)) | Err(mpsc::RecvTimeoutError::Disconnected) => return Err("screencast_helper_failed".into()),
                Err(mpsc::RecvTimeoutError::Timeout) => {}
            }
            if matches!(self.child.try_wait(), Ok(Some(_)) | Err(_)) {
                return Err("screencast_helper_failed".into());
            }
            if Instant::now() >= deadline {
                return Err("screencast_stream_timeout".into());
            }
        }
    }

    /// The reason the helper gave when it has stopped on its own.
    fn stopped(&mut self) -> Option<String> {
        let mut failure = None;
        while let Ok(line) = self.lines.try_recv() {
            if let HelperLine::Failed(reason) = line {
                failure = Some(reason);
            }
        }
        if failure.is_none() && !matches!(self.child.try_wait(), Ok(Some(_)) | Err(_)) {
            return None;
        }
        // The reason is written just before the helper exits; give the reader a moment for it.
        let failure = failure.or_else(|| match self.lines.recv_timeout(Duration::from_millis(200)) {
            Ok(HelperLine::Failed(reason)) => Some(reason),
            _ => None,
        });
        Some(failure.unwrap_or_else(|| "exited".to_owned()))
    }

    fn stop(&mut self) {
        // Closing the lifeline lets the helper mark the frame file as over and remove it.
        self.lifeline = None;
        let deadline = Instant::now() + Duration::from_secs(1);
        while Instant::now() < deadline && matches!(self.child.try_wait(), Ok(None)) {
            std::thread::sleep(Duration::from_millis(10));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        // A killed helper leaves its file; the backend must not keep reading the last picture.
        let _ = std::fs::remove_file(&self.frame);
    }
}

impl Drop for Helper {
    fn drop(&mut self) {
        self.stop();
    }
}

enum Signal {
    Nothing,
    /// The desktop closed our session: the window is gone, or the user stopped sharing there.
    Closed,
    /// The portal, its desktop backend or the bus went away.
    Lost,
}

struct Portal {
    connection: Connection,
    destination: String,
    sender: String,
    counter: u32,
    request_path: Option<String>,
    session: Option<OwnedObjectPath>,
    signals: MessageStream,
    owners: MessageStream,
    backends: MessageStream,
}

/// A match for `NameOwnerChanged`; the caller narrows it to the names it watches.
fn owner_changes() -> Result<zbus::match_rule::Builder<'static>, String> {
    MatchRule::builder().msg_type(zbus::message::Type::Signal)
        .sender("org.freedesktop.DBus").map_err(failure("portal_unavailable"))?
        .interface("org.freedesktop.DBus").map_err(failure("portal_unavailable"))?
        .member("NameOwnerChanged").map_err(failure("portal_unavailable"))
}

impl Portal {
    /// A connection of its own: the app id has to be registered before any other portal call on it.
    fn open(check: &dyn Fn() -> Result<(), String>) -> Result<Self, String> {
        check()?;
        ensure_desktop_file()?;
        let deadline = Instant::now() + SETUP_TIMEOUT;
        let connection = wait_until(deadline, check, Connection::session())?.map_err(failure("portal_unavailable"))?;
        // Without the registration (an older portal) the request still works; the desktop then
        // shows no app name in its dialog and remembers the choice for an unnamed app.
        let registered = wait_until(deadline, check, connection.call_method(
            Some(DESTINATION), DESKTOP, Some("org.freedesktop.host.portal.Registry"), "Register",
            &(APP_ID, HashMap::<&str, Value>::new()),
        ))?;
        if registered.is_err() {
            crate::startup_log("Window sharing: the portal did not accept the app id");
        }
        // Watch owner changes before resolving the owner, so a replacement is not missed.
        let owners = owner_changes()?.add_arg(DESTINATION).map_err(failure("portal_unavailable"))?.build();
        let owners = wait_until(deadline, check, MessageStream::for_match_rule(owners, &connection, Some(8)))?
            .map_err(failure("portal_unavailable"))?;
        let backends = owner_changes()?.arg0ns(BACKENDS).map_err(failure("portal_unavailable"))?.build();
        let backends = wait_until(deadline, check, MessageStream::for_match_rule(backends, &connection, Some(8)))?
            .map_err(failure("portal_unavailable"))?;
        let reply = wait_until(deadline, check, connection.call_method(
            Some("org.freedesktop.DBus"), "/org/freedesktop/DBus", Some("org.freedesktop.DBus"), "GetNameOwner", &(DESTINATION,),
        ))?.map_err(failure("portal_unavailable"))?;
        let destination: String = reply.body().deserialize().map_err(failure("portal_unavailable"))?;
        let rule = MatchRule::builder().msg_type(zbus::message::Type::Signal)
            .sender(destination.as_str()).map_err(failure("portal_unavailable"))?
            .interface("org.freedesktop.portal.Session").map_err(failure("portal_unavailable"))?
            .member("Closed").map_err(failure("portal_unavailable"))?.build().to_owned();
        let signals = wait_until(deadline, check, MessageStream::for_match_rule(rule, &connection, Some(8)))?
            .map_err(failure("portal_unavailable"))?;
        let sender = connection.unique_name().ok_or("portal_unavailable")?.trim_start_matches(':').replace('.', "_");
        Ok(Self { connection, destination, sender, counter: 0, request_path: None, session: None, signals, owners, backends })
    }

    fn property(&self, deadline: Instant, check: &dyn Fn() -> Result<(), String>, name: &str) -> Result<Option<u32>, String> {
        Ok(wait_until(deadline, check, async {
            Proxy::new(&self.connection, self.destination.as_str(), DESKTOP, INTERFACE).await?.get_property::<u32>(name).await
        })?.ok())
    }

    fn token(&mut self) -> String {
        self.counter += 1;
        format!("vrct_vox_cast_{}_{}", std::process::id(), self.counter)
    }

    /// Calls a request-returning method and waits for its `Response`, subscribing first so a
    /// fast response cannot be missed.
    fn request<B>(&mut self, deadline: Instant, check: &dyn Fn() -> Result<(), String>, method: &str, token: &str, body: &B)
        -> Result<HashMap<String, OwnedValue>, String>
    where
        B: serde::Serialize + zbus::zvariant::DynamicType,
    {
        check()?;
        let path = format!("{DESKTOP}/request/{}/{token}", self.sender);
        self.request_path = Some(path.clone());
        let results: Result<HashMap<String, OwnedValue>, String> = wait_until(deadline, check, async {
            let request = Proxy::new(&self.connection, self.destination.as_str(), path.as_str(), "org.freedesktop.portal.Request")
                .await.map_err(failure("portal_unavailable"))?;
            let mut responses = request.receive_signal("Response").await.map_err(failure("portal_unavailable"))?;
            let portal = Proxy::new(&self.connection, self.destination.as_str(), DESKTOP, INTERFACE)
                .await.map_err(failure("portal_unavailable"))?;
            check()?;
            let _: OwnedObjectPath = portal.call(method, body).await.map_err(failure("portal_request_failed"))?;
            let message = next(&mut responses).await.ok_or("portal_request_failed")?;
            let (code, results): (u32, HashMap<String, OwnedValue>) =
                message.body().deserialize().map_err(failure("portal_request_failed"))?;
            match code {
                0 => Ok(results),
                1 => Err("portal_cancelled".into()),
                _ => Err("portal_request_failed".into()),
            }
        })?;
        let results = results?;
        self.request_path = None;
        Ok(results)
    }

    /// Asks the user for a window (or restores the remembered one) and returns its PipeWire node,
    /// the connection to read it with, and the token for next time.
    fn share(&mut self, check: &dyn Fn() -> Result<(), String>, restore_token: Option<&str>) -> Result<(u32, OwnedFd, Started), String> {
        let setup = Instant::now() + SETUP_TIMEOUT;
        let version = self.property(setup, check, "version")?.ok_or("screencast_unsupported")?;
        let sources = self.property(setup, check, "AvailableSourceTypes")?.unwrap_or(0);
        if version < 1 || sources & SOURCE_WINDOW == 0 {
            return Err("screencast_unsupported".into());
        }
        let cursor_modes = if version >= 2 { self.property(setup, check, "AvailableCursorModes")?.unwrap_or(0) } else { 0 };

        let (token, session_token) = (self.token(), self.token());
        // Record the predictable handle before sending CreateSession, so cleanup also covers a
        // session whose Response has not arrived yet.
        self.session = Some(OwnedObjectPath::try_from(format!("{DESKTOP}/session/{}/{session_token}", self.sender))
            .map_err(|_| "portal_request_failed")?);
        let options = HashMap::from([
            ("handle_token", Value::from(token.as_str())),
            ("session_handle_token", Value::from(session_token.as_str())),
        ]);
        let session = session_handle(&self.request(setup, check, "CreateSession", &token, &(options,))?)?;
        self.session = Some(session.clone());

        let token = self.token();
        let options = select_options(&token, version, cursor_modes, restore_token);
        self.request(Instant::now() + SETUP_TIMEOUT, check, "SelectSources", &token, &(&session, options))?;

        let token = self.token();
        let options = HashMap::from([("handle_token", Value::from(token.as_str()))]);
        let results = self.request(Instant::now() + DIALOG_TIMEOUT, check, "Start", &token, &(&session, "", options))?;
        let (node, started) = started(&results)?;

        let reply = wait_until(Instant::now() + SETUP_TIMEOUT, check, self.connection.call_method(
            Some(self.destination.as_str()), DESKTOP, Some(INTERFACE), "OpenPipeWireRemote",
            &(&session, HashMap::<&str, Value>::new()),
        ))?.map_err(failure("portal_request_failed"))?;
        let remote: zbus::zvariant::OwnedFd = reply.body().deserialize().map_err(failure("portal_request_failed"))?;
        Ok((node, remote.into(), started))
    }

    /// Looks at the bus for a moment. Never blocks longer than `slice`.
    fn poll(&mut self, slice: Duration) -> Signal {
        let (signals, owners, backends) = (&mut self.signals, &mut self.owners, &mut self.backends);
        let message = wait_until(Instant::now() + slice, || Ok(()), poll_fn(|context| {
            if let Poll::Ready(message) = Pin::new(&mut *owners).poll_next(context) { return Poll::Ready(message); }
            if let Poll::Ready(message) = Pin::new(&mut *backends).poll_next(context) { return Poll::Ready(message); }
            Pin::new(&mut *signals).poll_next(context)
        }));
        let message = match message {
            Err(_) => return Signal::Nothing,
            Ok(Some(Ok(message))) => message,
            Ok(_) => return Signal::Lost,
        };
        let header = message.header();
        if header.member().map(|name| name.as_str()) == Some("NameOwnerChanged") {
            return match message.body().deserialize::<(String, String, String)>() {
                Ok((name, old, _new)) if portal_owner_lost(&name, &old) => Signal::Lost,
                _ => Signal::Nothing,
            };
        }
        let ours = self.session.as_ref().map(|path| path.as_str());
        if ours.is_some() && header.path().map(|path| path.as_str()) == ours {
            // The desktop has already closed it; closing it again would only fail.
            self.session = None;
            return Signal::Closed;
        }
        Signal::Nothing
    }

    fn close_path(&self, path: &str, interface: &str) {
        let _ = wait_until(Instant::now() + Duration::from_secs(1), || Ok(()),
            self.connection.call_method(Some(self.destination.as_str()), path, Some(interface), "Close", &()));
    }
}

impl Drop for Portal {
    fn drop(&mut self) {
        // An unanswered request (its dialog), then the session: the desktop stops the stream with it.
        if let Some(path) = self.request_path.take() {
            self.close_path(&path, "org.freedesktop.portal.Request");
        }
        if let Some(session) = self.session.take() {
            self.close_path(session.as_str(), "org.freedesktop.portal.Session");
        }
        let _ = wait_until(Instant::now() + Duration::from_secs(1), || Ok(()), self.connection.clone().close());
    }
}

/// One sharing, from the request to its end. Runs on its own thread, which is also the parent the
/// helper is tied to: when this thread ends, the kernel ends the helper.
fn run(app: AppHandle, program: PathBuf, frame: PathBuf, restore_token: Option<String>, stop: Arc<AtomicBool>,
    reply: mpsc::Sender<Result<Started, String>>) {
    let check = || if stop.load(Ordering::Acquire) { Err("portal_cancelled".to_owned()) } else { Ok(()) };
    let opened = Portal::open(&check).and_then(|mut portal| {
        let (node, remote, started) = portal.share(&check, restore_token.as_deref())?;
        // Declared after the portal, so the helper stops first when both go away.
        let mut helper = Helper::start(&program, remote, node, &frame)?;
        helper.wait_streaming(check)?;
        Ok((portal, helper, started))
    });
    let (mut portal, mut helper) = match opened {
        Ok((portal, helper, started)) => {
            // Nobody is waiting for the answer any more (the page went away): do not keep sharing.
            if reply.send(Ok(started)).is_err() {
                return;
            }
            (portal, helper)
        }
        Err(code) => {
            let _ = reply.send(Err(code));
            return;
        }
    };
    let reason = loop {
        if stop.load(Ordering::Acquire) {
            break end_reason(true, false, None);
        }
        if let Some(failure) = helper.stopped() {
            break end_reason(false, false, Some(&failure));
        }
        match portal.poll(Duration::from_millis(200)) {
            Signal::Nothing => {}
            Signal::Closed => break end_reason(false, true, None),
            Signal::Lost => break end_reason(false, false, None),
        }
    };
    drop(helper);
    drop(portal);
    if let Some(reason) = reason {
        crate::startup_log(&format!("Window sharing is over: {reason}"));
        let _ = app.emit_to("main", "screencast-ended", Ended { reason });
    }
}

async fn finish(state: &Screencast) {
    state.cancel();
    if let Some(running) = state.take() {
        let _ = tauri::async_runtime::spawn_blocking(move || running.thread.join()).await;
    }
}

/// Whether the button for sharing a window belongs on this desktop, and whether a window is shared now.
#[tauri::command]
pub fn screencast_support(window: WebviewWindow, state: State<'_, Screencast>) -> Result<Support, String> {
    if window.label() != "main" {
        return Err("screencast_forbidden".into());
    }
    Ok(Support { supported: crate::quick_chat::wayland_session(), active: state.active() })
}

/// Asks the desktop to share one window with chat reading. Call only on the user's request: the
/// button in the settings, or turning chat reading on where a window was shared before.
/// A sharing that is already running is replaced.
#[tauri::command]
pub async fn screencast_start(window: WebviewWindow, app: AppHandle, state: State<'_, Screencast>, restore_token: Option<String>)
    -> Result<Started, String> {
    if window.label() != "main" {
        return Err("screencast_forbidden".into());
    }
    if !crate::quick_chat::wayland_session() {
        return Err("screencast_unavailable".into());
    }
    let frame = frame_path().ok_or("screencast_unavailable")?;
    let program = helper_path().ok_or("screencast_helper_missing")?;
    // A request that is still waiting for its dialog gives way to this one.
    state.cancel();
    let _serial = SERIAL.lock().await;
    finish(&state).await;

    let stop = Arc::new(AtomicBool::new(false));
    let (reply, result) = mpsc::channel();
    let thread = {
        let stop = stop.clone();
        std::thread::Builder::new().name("vrct-portal-screencast".into())
            .spawn(move || run(app, program, frame, restore_token, stop, reply))
            .map_err(|_| "screencast_unavailable")?
    };
    *state.0.lock().map_err(|_| "screencast_unavailable")? = Some(Running { stop: stop.clone(), thread });
    // Kept in the command future: when the caller goes away before the answer, the request and
    // anything it has started are given up.
    struct StopOnDrop(Arc<AtomicBool>, bool);
    impl Drop for StopOnDrop {
        fn drop(&mut self) {
            if !self.1 {
                self.0.store(true, Ordering::Release);
            }
        }
    }
    let mut guard = StopOnDrop(stop, false);
    let limit = SETUP_TIMEOUT * 4 + DIALOG_TIMEOUT + STREAM_TIMEOUT;
    let answer = tauri::async_runtime::spawn_blocking(move || result.recv_timeout(limit)).await.map_err(|_| "portal_unavailable")?;
    let started = answer.map_err(|_| "portal_timeout".to_owned())??;
    guard.1 = true;
    Ok(started)
}

/// Ends the sharing: the helper stops and the desktop is told the session is over.
#[tauri::command]
pub async fn screencast_stop(window: WebviewWindow, state: State<'_, Screencast>) -> Result<(), String> {
    if window.label() != "main" {
        return Err("screencast_forbidden".into());
    }
    state.cancel();
    let _serial = SERIAL.lock().await;
    finish(&state).await;
    Ok(())
}

/// The app is exiting: end the sharing before the process goes away.
pub fn shutdown<R: tauri::Runtime>(app: &AppHandle<R>) {
    let Some(state) = app.try_state::<Screencast>() else { return };
    state.cancel();
    if let Some(running) = state.take() {
        let _ = running.thread.join();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn results(entries: Vec<(&str, Value<'_>)>) -> HashMap<String, OwnedValue> {
        entries.into_iter().map(|(key, value)| (key.to_owned(), OwnedValue::try_from(value).unwrap())).collect()
    }

    fn streams(nodes: &[u32]) -> Value<'static> {
        let streams: Vec<(u32, HashMap<String, Value<'static>>)> = nodes.iter()
            .map(|node| (*node, HashMap::from([("source_type".to_owned(), Value::from(SOURCE_WINDOW))])))
            .collect();
        Value::from(streams)
    }

    #[test]
    fn asks_for_one_window_without_the_pointer_and_remembers_the_choice() {
        let options = select_options("t1", 5, 7, Some("saved"));
        assert_eq!(options["handle_token"], Value::from("t1"));
        assert_eq!(options["types"], Value::from(2u32));
        assert_eq!(options["multiple"], Value::from(false));
        assert_eq!(options["cursor_mode"], Value::from(1u32));
        assert_eq!(options["persist_mode"], Value::from(2u32));
        assert_eq!(options["restore_token"], Value::from("saved"));
        assert_eq!(options.len(), 6);
    }

    #[test]
    fn leaves_out_what_the_desktop_does_not_support() {
        // No saved token: the desktop asks, and still remembers the answer.
        let first = select_options("t1", 4, 1, None);
        assert!(first.contains_key("persist_mode") && !first.contains_key("restore_token"));
        // Before version 4 there is no restoring; an unknown option would fail the request.
        let old = select_options("t1", 3, 1, Some("saved"));
        assert!(!old.contains_key("persist_mode") && !old.contains_key("restore_token"));
        // The pointer can only be embedded or sent as metadata here: say nothing rather than ask for it.
        assert!(!select_options("t1", 5, 6, None).contains_key("cursor_mode"));
        // A token that is not one is not sent.
        assert!(!select_options("t1", 5, 1, Some("")).contains_key("restore_token"));
    }

    #[test]
    fn only_plain_tokens_are_used() {
        assert_eq!(usable_token(Some("0b3c9f2e-token")), Some("0b3c9f2e-token"));
        assert_eq!(usable_token(None), None);
        assert_eq!(usable_token(Some("")), None);
        assert_eq!(usable_token(Some("a\nb")), None);
        let long = "x".repeat(TOKEN_LIMIT + 1);
        assert_eq!(usable_token(Some(&long)), None);
        assert_eq!(usable_token(Some(&long[..TOKEN_LIMIT])), Some(&long[..TOKEN_LIMIT]));
    }

    #[test]
    fn a_start_response_names_the_node_and_the_next_token() {
        let response = results(vec![("streams", streams(&[57])), ("restore_token", Value::from("next"))]);
        assert_eq!(started(&response), Ok((57, Started { restore_token: Some("next".into()) })));
        // The desktop may not hand out a token (the user chose not to be remembered).
        let once = results(vec![("streams", streams(&[58]))]);
        assert_eq!(started(&once), Ok((58, Started { restore_token: None })));
        let odd = results(vec![("streams", streams(&[59])), ("restore_token", Value::from(""))]);
        assert_eq!(started(&odd), Ok((59, Started { restore_token: None })));
    }

    #[test]
    fn a_start_response_without_a_stream_is_a_failure() {
        assert_eq!(started(&results(vec![])), Err("portal_request_failed".into()));
        assert_eq!(started(&results(vec![("streams", streams(&[]))])), Err("portal_request_failed".into()));
        assert_eq!(started(&results(vec![("streams", Value::from("57"))])), Err("portal_request_failed".into()));
    }

    #[test]
    fn a_session_handle_is_a_path_as_text_or_as_a_path() {
        let path = "/org/freedesktop/portal/desktop/session/1_42/vrct_vox_cast_7_2";
        let as_text = results(vec![("session_handle", Value::from(path))]);
        assert_eq!(session_handle(&as_text).unwrap().as_str(), path);
        let as_path = results(vec![("session_handle", Value::from(zbus::zvariant::ObjectPath::try_from(path).unwrap()))]);
        assert_eq!(session_handle(&as_path).unwrap().as_str(), path);
        assert!(session_handle(&results(vec![])).is_err());
        assert!(session_handle(&results(vec![("session_handle", Value::from("not a path"))])).is_err());
    }

    #[test]
    fn the_helper_is_looked_for_in_the_package_then_in_the_checkout() {
        // The archive: the app sits beside `_internal`.
        let packaged = helper_candidates(Path::new("/opt/VRCT-VOX/vrct-vox"), None);
        assert_eq!(packaged[0], PathBuf::from("/opt/VRCT-VOX/_internal/build/vrct-screen-capture"));
        // The AppImage: the app is in usr/bin, the backend's files under usr/lib/vrct-vox.
        let appimage = helper_candidates(Path::new("/tmp/.mount_x/usr/bin/vrct-vox"), None);
        assert_eq!(appimage, vec![
            PathBuf::from("/tmp/.mount_x/usr/bin/_internal/build/vrct-screen-capture"),
            PathBuf::from("/tmp/.mount_x/usr/lib/vrct-vox/_internal/build/vrct-screen-capture"),
        ]);
        let development = helper_candidates(Path::new("/src/src-tauri/target/debug/vrct-vox"), Some(Path::new("/src")));
        assert_eq!(development.last(), Some(&PathBuf::from("/src/build/vrct-screen-capture")));
        assert_eq!(development.len(), 3);
    }

    #[test]
    fn inside_the_appimage_the_helper_loads_the_hosts_libraries() {
        // Not the AppImage: the environment is left as it is.
        assert_eq!(host_library_path(None, None), None);
        assert_eq!(host_library_path(None, Some("/ignored")), None);
        // The host had a value before the AppImage put its own libraries first.
        assert_eq!(host_library_path(Some("x"), Some("/opt/lib")), Some(Some("/opt/lib".into())));
        assert_eq!(host_library_path(Some("x"), None), Some(Some(String::new())));
        // The host had none: the helper gets none.
        assert_eq!(host_library_path(Some(""), Some("")), Some(None));
    }

    #[test]
    fn helper_lines_are_its_two_messages_and_nothing_else() {
        assert_eq!(helper_line("streaming"), Some(HelperLine::Streaming));
        assert_eq!(helper_line("screen_capture_stream_ended\n"), Some(HelperLine::Failed("stream_ended".into())));
        for other in ["", "streaming now", "screen_capture_", "screen_capture_Bad", "screen_capture_a b",
            "[W] pw.context: something", "asr_capture_stalled"] {
            assert_eq!(helper_line(other), None, "{other:?}");
        }
    }

    #[test]
    fn the_page_hears_why_sharing_is_over_unless_the_app_ended_it() {
        // Stopped by the app (chat reading turned off, the button, exit): nothing to report.
        assert_eq!(end_reason(true, false, None), None);
        assert_eq!(end_reason(true, true, Some("stream_ended")), None);
        // The window was closed or sharing was stopped from the desktop.
        assert_eq!(end_reason(false, true, None), Some("ended"));
        assert_eq!(end_reason(false, false, Some("stream_ended")), Some("ended"));
        // Anything else is a failure: the helper broke, or the portal went away.
        assert_eq!(end_reason(false, false, Some("format_unsupported")), Some("failed"));
        assert_eq!(end_reason(false, false, Some("exited")), Some("failed"));
        assert_eq!(end_reason(false, false, None), Some("failed"));
    }
}
