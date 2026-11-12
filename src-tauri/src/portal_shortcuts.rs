//! Global shortcuts on native Wayland through the XDG GlobalShortcuts portal.
//!
//! Wayland gives no client a global key grab, so the X11 shortcut plugin only
//! sees keys while an XWayland window has focus. The portal asks the desktop
//! (KWin, GNOME Shell) to bind the keys and reports each press as a signal,
//! which is forwarded to the main window as `portal-shortcut`.
//!
//! One worker thread owns a dedicated session-bus connection: the host app
//! registry requires `Register` before any other portal call on a connection.
use std::collections::HashMap;
use std::path::PathBuf;
use std::future::{poll_fn, Future};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::task::Poll;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, State, WebviewWindow};
use zbus::{Connection, MatchRule, MessageStream, Proxy};
// zbus is pinned; its macro support re-export avoids adding a new dependency.
use zbus::export::futures_core::Stream;
#[path = "portal_shortcut_worker.rs"]
pub(crate) mod worker;
use worker::{Backend, Mailbox, Operation, Worker};
use zbus::zvariant::{OwnedObjectPath, OwnedValue, Value};

/// Must match a desktop file the portal can find; see `ensure_desktop_file`.
pub(crate) const APP_ID: &str = "io.github.kein5.vrct-vox";
pub(crate) const DESTINATION: &str = "org.freedesktop.portal.Desktop";
pub(crate) const DESKTOP: &str = "/org/freedesktop/portal/desktop";
const INTERFACE: &str = "org.freedesktop.portal.GlobalShortcuts";
/// The desktop's own portal processes (`...desktop.kde`, `...desktop.gnome`). They hold the
/// dialog and the key grabs; the frontend keeps its name and our session when one restarts.
pub(crate) const BACKENDS: &str = "org.freedesktop.impl.portal.desktop";
const MARKER: &str = "X-VRCT-VOX-Generated=true";
/// The desktop may show a confirmation dialog while binding.
const BIND_TIMEOUT: Duration = Duration::from_secs(180);
const ACTIONS: [(&str, &str); 9] = [
    ("open_quick_chat", "Open the quick chat window"),
    ("toggle_vrct_visibility", "Minimize or restore VRCT-VOX"),
    ("toggle_translation", "Turn translation on or off"),
    ("toggle_transcription_send", "Turn microphone input on or off"),
    ("toggle_transcription_receive", "Turn listening on or off"),
    ("stop_voice", "Stop speech and clear the queue"),
    ("toggle_voice_mute", "Mute or resume the VRCT-VOX voice"),
    ("toggle_tts", "Turn TTS on or off"),
    ("toggle_rvc", "Turn RVC on or off"),
];

/// (action id, portal trigger, Qt key code for KDE when representable)
type Binding = Vec<(String, String, Option<i32>)>;
type Jobs = Mailbox<Binding, HashMap<String, Assigned>>;

/// The key the desktop actually uses for one action. `applied` is false when
/// the desktop kept another key (for example one taken by another app), and
/// unknown on desktops whose assignment cannot be read back.
#[derive(Clone, Serialize)]
pub struct Assigned {
    shown: String,
    applied: Option<bool>,
}

#[derive(Default)]
pub struct PortalShortcuts(Mutex<Option<Arc<Jobs>>>);

#[derive(Clone, Serialize)]
struct Activation {
    id: String,
    activation_token: Option<String>,
}

pub(crate) fn failure(code: &str) -> impl Fn(zbus::Error) -> String + '_ {
    move |_| code.to_owned()
}

/// VRCT stores keys as shown in the UI ("Ctrl", "Shift", "Q"); the portal
/// takes the shortcuts specification's names ("CTRL+SHIFT+q").
fn trigger(keys: &[String]) -> Option<String> {
    let mut parts = Vec::new();
    let mut key = None;
    for name in keys {
        match name.as_str() {
            "Ctrl" => parts.push("CTRL".to_owned()),
            "Shift" => parts.push("SHIFT".to_owned()),
            "Alt" => parts.push("ALT".to_owned()),
            "Super" | "Meta" => parts.push("LOGO".to_owned()),
            other if key.is_none() => {
                let mut chars = other.chars();
                key = Some(match (chars.next(), chars.next()) {
                    (Some(' '), None) => "space".to_owned(),
                    (Some(c), None) if c.is_ascii_alphanumeric() => c.to_ascii_lowercase().to_string(),
                    (Some(_), None) => return None,
                    _ => match other {
                        "Space" => "space".to_owned(),
                        "Enter" => "Return".to_owned(),
                        "ArrowUp" => "Up".to_owned(),
                        "ArrowDown" => "Down".to_owned(),
                        "ArrowLeft" => "Left".to_owned(),
                        "ArrowRight" => "Right".to_owned(),
                        _ if other.chars().all(|c| c.is_ascii_alphanumeric()) => other.to_owned(),
                        _ => return None,
                    },
                });
            }
            _ => return None,
        }
    }
    parts.push(key?);
    Some(parts.join("+"))
}

const QT_SHIFT: i32 = 0x0200_0000;
const QT_CTRL: i32 = 0x0400_0000;
const QT_ALT: i32 = 0x0800_0000;
const QT_META: i32 = 0x1000_0000;
const QT_NAMED: [(&str, i32); 15] = [
    ("Escape", 0x0100_0000), ("Tab", 0x0100_0001), ("Backspace", 0x0100_0003), ("Enter", 0x0100_0004),
    ("Insert", 0x0100_0006), ("Delete", 0x0100_0007), ("Home", 0x0100_0010), ("End", 0x0100_0011),
    ("ArrowLeft", 0x0100_0012), ("ArrowUp", 0x0100_0013), ("ArrowRight", 0x0100_0014),
    ("ArrowDown", 0x0100_0015), ("PageUp", 0x0100_0016), ("PageDown", 0x0100_0017), ("Space", 0x20),
];

/// KDE stores shortcuts as Qt key combinations (`QKeyCombination::toCombined`).
fn qt_key(keys: &[String]) -> Option<i32> {
    let mut combined = 0;
    let mut key = None;
    for name in keys {
        match name.as_str() {
            "Ctrl" => combined |= QT_CTRL,
            "Shift" => combined |= QT_SHIFT,
            "Alt" => combined |= QT_ALT,
            "Super" | "Meta" => combined |= QT_META,
            other if key.is_none() => {
                let mut chars = other.chars();
                key = Some(match (chars.next(), chars.next()) {
                    (Some(' '), None) => 0x20,
                    (Some(c), None) if c.is_ascii_alphanumeric() => c.to_ascii_uppercase() as i32,
                    _ => match other.strip_prefix('F').and_then(|n| n.parse::<i32>().ok()) {
                        Some(n @ 1..=35) => 0x0100_0030 + n - 1,
                        _ => QT_NAMED.iter().find(|(named, _)| *named == other)?.1,
                    },
                });
            }
            _ => return None,
        }
    }
    Some(combined | key?)
}

fn qt_text(combined: i32) -> String {
    let mut text = String::new();
    for (bit, name) in [(QT_META, "Meta+"), (QT_CTRL, "Ctrl+"), (QT_ALT, "Alt+"), (QT_SHIFT, "Shift+")] {
        if combined & bit != 0 {
            text.push_str(name);
        }
    }
    let key = combined & 0x01FF_FFFF;
    match key {
        0x21..=0x7E => text.push(key as u8 as char),
        0x0100_0030..=0x0100_0052 => text.push_str(&format!("F{}", key - 0x0100_0030 + 1)),
        _ => text.push_str(QT_NAMED.iter().find(|(_, code)| *code == key).map_or("?", |(name, _)| *name)),
    }
    text
}

fn quote(path: &str) -> String {
    let mut out = String::from("\"");
    for c in path.chars() {
        if matches!(c, '"' | '`' | '$' | '\\') {
            out.push('\\');
        }
        out.push(c);
    }
    out.push('"');
    out
}

/// The portal identifies a host app only by an installed desktop file. Write
/// one for this executable unless a packager or the user already provides it.
pub(crate) fn ensure_desktop_file() -> Result<(), String> {
    let data = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/share")))
        .ok_or("portal_desktop_file_failed")?;
    let directory = data.join("applications");
    let path = directory.join(format!("{APP_ID}.desktop"));
    let current = std::env::current_exe().map_err(|_| "portal_desktop_file_failed")?;
    // APPIMAGE is inherited by children of any AppImage; trust it only when
    // this executable runs from that image's own mount (APPDIR).
    let mounted = std::env::var_os("APPDIR").is_some_and(|directory| current.starts_with(directory));
    let executable = std::env::var_os("APPIMAGE")
        .map(PathBuf::from)
        .filter(|path| mounted && path.is_absolute())
        .unwrap_or(current);
    let executable = executable.to_str().ok_or("portal_desktop_file_failed")?;
    let content = format!(
        "[Desktop Entry]\nType=Application\nName=VRCT-VOX\n\
         Comment=Speech, voice conversion and translated chat\nExec={}\nIcon=vrct-vox\n\
         Terminal=false\nCategories=AudioVideo;Audio;Network;\nStartupWMClass=vrct-vox\n{MARKER}\n",
        quote(executable)
    );
    match std::fs::read_to_string(&path) {
        Ok(existing) if existing == content || !existing.contains(MARKER) => return Ok(()),
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err("portal_desktop_file_failed".into()),
    }
    std::fs::create_dir_all(&directory).map_err(|_| "portal_desktop_file_failed")?;
    let temporary = directory.join(format!(".{APP_ID}.desktop.tmp"));
    std::fs::write(&temporary, content)
        .and_then(|()| std::fs::rename(&temporary, &path))
        .map_err(|_| {
            let _ = std::fs::remove_file(&temporary);
            "portal_desktop_file_failed".to_owned()
        })
}

struct Portal {
    connection: Connection,
    destination: String,
    sender: String,
    counter: u32,
    request_path: Option<String>,
    session: Arc<Mutex<Option<OwnedObjectPath>>>,
    alive: Arc<AtomicBool>,
    listener: Option<std::thread::JoinHandle<()>>,
    retired: bool,
}

pub(crate) async fn next<S: Stream + Unpin>(stream: &mut S) -> Option<S::Item> {
    poll_fn(|context| Pin::new(&mut *stream).poll_next(context)).await
}

impl Portal {
    fn open(app: AppHandle, operation: &Operation) -> Result<Self, String> {
        operation.check()?;
        ensure_desktop_file()?;
        let connection = operation.wait(Connection::session())?.map_err(failure("portal_unavailable"))?;
        // Build the owner before any fallible setup, so failure closes the connection.
        let mut portal = Self {
            connection, destination: DESTINATION.into(), sender: String::new(), counter: 0,
            request_path: None, session: Arc::new(Mutex::new(None)),
            alive: Arc::new(AtomicBool::new(true)), listener: None, retired: false,
        };
        portal.initialize(app, operation)?;
        Ok(portal)
    }

    fn check(&self, operation: &Operation) -> Result<(), String> {
        operation.check()?;
        if self.alive.load(Ordering::Acquire) { Ok(()) } else { Err("portal_unavailable".into()) }
    }

    fn wait<F: Future>(&self, operation: &Operation, future: F) -> Result<F::Output, String> {
        worker::wait_until(operation.deadline, || self.check(operation), future)
    }

    fn initialize(&mut self, app: AppHandle, operation: &Operation) -> Result<(), String> {
        self.wait(operation, self.connection.call_method(
            Some(DESTINATION), DESKTOP, Some("org.freedesktop.host.portal.Registry"), "Register",
            &(APP_ID, HashMap::<&str, Value>::new()),
        ))?.map_err(failure("portal_app_id_unavailable"))?;
        // Watch owner changes before resolving the owner, including replacement.
        let owner_rule = MatchRule::builder().msg_type(zbus::message::Type::Signal)
            .sender("org.freedesktop.DBus").map_err(failure("portal_unavailable"))?
            .interface("org.freedesktop.DBus").map_err(failure("portal_unavailable"))?
            .member("NameOwnerChanged").map_err(failure("portal_unavailable"))?
            .add_arg(DESTINATION).map_err(failure("portal_unavailable"))?.build();
        let owners = self.wait(operation, MessageStream::for_match_rule(owner_rule, &self.connection, Some(8)))?
            .map_err(failure("portal_unavailable"))?;
        let backend_rule = MatchRule::builder().msg_type(zbus::message::Type::Signal)
            .sender("org.freedesktop.DBus").map_err(failure("portal_unavailable"))?
            .interface("org.freedesktop.DBus").map_err(failure("portal_unavailable"))?
            .member("NameOwnerChanged").map_err(failure("portal_unavailable"))?
            .arg0ns(BACKENDS).map_err(failure("portal_unavailable"))?.build();
        let backends = self.wait(operation, MessageStream::for_match_rule(backend_rule, &self.connection, Some(8)))?
            .map_err(failure("portal_unavailable"))?;
        let reply = self.wait(operation, self.connection.call_method(
            Some("org.freedesktop.DBus"), "/org/freedesktop/DBus", Some("org.freedesktop.DBus"),
            "GetNameOwner", &(DESTINATION,),
        ))?.map_err(failure("portal_unavailable"))?;
        self.destination = reply.body().deserialize().map_err(failure("portal_unavailable"))?;
        let rule = MatchRule::builder().msg_type(zbus::message::Type::Signal)
            .sender(self.destination.as_str()).map_err(failure("portal_unavailable"))?.build();
        let signals = self.wait(operation, MessageStream::for_match_rule(rule, &self.connection, Some(64)))?
            .map_err(failure("portal_unavailable"))?;
        let (connection, session, alive) = (self.connection.clone(), self.session.clone(), self.alive.clone());
        self.listener = Some(std::thread::Builder::new().name("vrct-portal-signals".into())
            .spawn(move || listen(connection, signals, owners, backends, session, alive, app))
            .map_err(|_| "portal_unavailable")?);
        let version: u32 = self.wait(operation, async {
            Proxy::new(&self.connection, self.destination.as_str(), DESKTOP, INTERFACE).await?
                .get_property("version").await
        })?.map_err(failure("portal_shortcuts_unsupported"))?;
        if version < 1 { return Err("portal_shortcuts_unsupported".into()); }
        self.sender = self.connection.unique_name().ok_or("portal_unavailable")?
            .trim_start_matches(':').replace('.', "_");
        Ok(())
    }

    fn token(&mut self) -> String {
        self.counter += 1;
        format!("vrct_vox_{}_{}", std::process::id(), self.counter)
    }

    /// Calls a request-returning method and waits for its `Response`,
    /// subscribing first so a fast response cannot be missed.
    fn request<B>(&mut self, operation: &Operation, method: &str, token: &str, body: &B) -> Result<HashMap<String, OwnedValue>, String>
    where
        B: serde::Serialize + zbus::zvariant::DynamicType,
    {
        self.check(operation)?;
        let path = format!("{DESKTOP}/request/{}/{token}", self.sender);
        self.request_path = Some(path.clone());
        let results: Result<HashMap<String, OwnedValue>, String> = self.wait(operation, async {
            let request = Proxy::new(&self.connection, self.destination.as_str(), path.as_str(), "org.freedesktop.portal.Request")
                .await.map_err(failure("portal_unavailable"))?;
            let mut responses = request.receive_signal("Response").await.map_err(failure("portal_unavailable"))?;
            let portal = Proxy::new(&self.connection, self.destination.as_str(), DESKTOP, INTERFACE)
                .await.map_err(failure("portal_unavailable"))?;
            self.check(operation)?;
            let _: OwnedObjectPath = portal.call(method, body).await.map_err(failure("portal_request_failed"))?;
            self.check(operation)?;
            let message = next(&mut responses).await.ok_or("portal_request_failed")?;
            self.check(operation)?;
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

    fn create_session(&mut self, operation: &Operation) -> Result<OwnedObjectPath, String> {
        let token = self.token();
        let session_token = self.token();
        // Record the predictable handle before sending CreateSession, so timeout
        // cleanup also covers a session whose Response has not arrived yet.
        let expected = OwnedObjectPath::try_from(format!("{DESKTOP}/session/{}/{session_token}", self.sender))
            .map_err(|_| "portal_request_failed")?;
        *self.session.lock().unwrap() = Some(expected);
        let options = HashMap::from([
            ("handle_token", Value::from(token.as_str())),
            ("session_handle_token", Value::from(session_token.as_str())),
        ]);
        let results = self.request(operation, "CreateSession", &token, &(options,))?;
        let handle = match results.get("session_handle").map(|value| &**value) {
            Some(Value::Str(path)) => path.as_str().to_owned(),
            Some(Value::ObjectPath(path)) => path.as_str().to_owned(),
            _ => return Err("portal_request_failed".into()),
        };
        let handle = OwnedObjectPath::try_from(handle).map_err(|_| "portal_request_failed")?;
        *self.session.lock().unwrap() = Some(handle.clone());
        Ok(handle)
    }

    fn bind_session(&mut self, session: &OwnedObjectPath, binding: &Binding, operation: &Operation) -> Result<HashMap<String, Assigned>, String> {
        let token = self.token();
        let shortcuts: Vec<(&str, HashMap<&str, Value>)> = binding
            .iter()
            .map(|(id, preferred, _)| {
                let description = ACTIONS.iter().find(|(action, _)| action == id).map_or("", |(_, text)| *text);
                (
                    id.as_str(),
                    HashMap::from([
                        ("description", Value::from(description)),
                        ("preferred_trigger", Value::from(preferred.as_str())),
                    ]),
                )
            })
            .collect();
        let options = HashMap::from([("handle_token", Value::from(token.as_str()))]);
        let results = self.request(operation, "BindShortcuts", &token, &(session, shortcuts, "", options))?;
        // Best effort: the desktop's own description of each assigned key.
        let described: HashMap<String, String> = results
            .get("shortcuts")
            .and_then(|value| value.try_clone().ok())
            .and_then(|value| Vec::<(String, HashMap<String, OwnedValue>)>::try_from(value).ok())
            .unwrap_or_default()
            .into_iter()
            .map(|(id, properties)| {
                let shown = properties
                    .get("trigger_description")
                    .and_then(|value| value.try_clone().ok())
                    .and_then(|value| String::try_from(value).ok())
                    .unwrap_or_default();
                (id, shown)
            })
            .collect();
        let mut assigned = HashMap::new();
        for (id, _, qt) in binding {
            self.check(operation)?;
            let row = if let Some(key) = qt { self.apply_on_kde(id, *key, operation)? } else { None };
            self.check(operation)?;
            assigned.insert(id.clone(), row.unwrap_or_else(|| Assigned {
                shown: described.get(id).cloned().unwrap_or_default(), applied: None,
            }));
        }
        Ok(assigned)
    }

    /// A portal's preferred trigger only seeds a new shortcut: KDE keeps the
    /// key chosen in its first dialog even after VRCT changes. Make VRCT's
    /// setting authoritative the way System Settings edits a shortcut, then
    /// read back what KDE kept (it refuses keys taken by other components).
    fn apply_on_kde(&self, id: &str, key: i32, operation: &Operation) -> Result<Option<Assigned>, String> {
        let description = ACTIONS.iter().find(|(action, _)| *action == id).map_or("", |(_, text)| *text);
        let action = [APP_ID, id, "VRCT-VOX", description];
        self.wait(operation, async {
            let accel = Proxy::new(&self.connection, "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel").await.ok()?;
            let first = |keys: Vec<(Vec<i32>,)>| keys.into_iter().next().and_then(|(codes,)| codes.into_iter().next());
            let mut current = first(accel.call("shortcutKeys", &(action.as_slice(),)).await.ok()?);
            // In particular, an expired portal Response must never change KDE's keys.
            self.check(operation).ok()?;
            if current != Some(key) {
                let _: () = accel.call("setForeignShortcutKeys", &(action.as_slice(), vec![(vec![key, 0, 0, 0],)]))
                    .await.ok()?;
                self.check(operation).ok()?;
                current = first(accel.call("shortcutKeys", &(action.as_slice(),)).await.ok()?);
            }
            Some(Assigned {
                shown: current.filter(|code| *code != 0).map(qt_text).unwrap_or_default(),
                applied: Some(current == Some(key)),
            })
        })
    }

    fn close_path(&self, path: &str, interface: &str) -> Result<(), String> {
        // Cleanup has its own short budget: the original operation is already
        // cancelled. Closing the connection below is the fallback on failure.
        worker::wait_until(Instant::now() + Duration::from_secs(1), || Ok(()),
            self.connection.call_method(Some(self.destination.as_str()), path, Some(interface), "Close", &()))?
            .map_err(failure("portal_unavailable"))?;
        Ok(())
    }

    fn close_session(&mut self) -> Result<(), String> {
        let old = self.session.lock().unwrap().take();
        if let Some(old) = old { self.close_path(old.as_str(), "org.freedesktop.portal.Session")?; }
        Ok(())
    }
}

impl Backend for Portal {
    type Binding = Binding;
    type Assigned = HashMap<String, Assigned>;
    fn alive(&self) -> bool { self.alive.load(Ordering::Acquire) }
    fn bind(&mut self, binding: &Binding, operation: &Operation) -> Result<Self::Assigned, String> {
        self.close_session()?;
        self.check(operation)?;
        if binding.is_empty() { return Ok(HashMap::new()); }
        let handle = self.create_session(operation)?;
        self.bind_session(&handle, binding, operation)
    }
    fn close(&mut self) {
        if self.retired { return; }
        self.retired = true;
        self.alive.store(false, Ordering::Release);
        if let Some(path) = self.request_path.take() { let _ = self.close_path(&path, "org.freedesktop.portal.Request"); }
        let _ = self.close_session();
        let _ = worker::wait_until(Instant::now() + Duration::from_secs(1), || Ok(()), self.connection.clone().close());
        if let Some(listener) = self.listener.take() { let _ = listener.join(); }
    }
}
impl Drop for Portal {
    fn drop(&mut self) { self.close(); }
}

/// Whether a `NameOwnerChanged` means the portal that holds our shortcuts went away or was
/// replaced. A name that only appears (no old owner) took nothing with it.
pub(crate) fn portal_owner_lost(name: &str, old_owner: &str) -> bool {
    let backend = name.strip_prefix(BACKENDS).is_some_and(|rest| rest.is_empty() || rest.starts_with('.'));
    (name == DESTINATION || backend) && !old_owner.is_empty()
}

fn listen(connection: Connection, mut signals: MessageStream, mut owners: MessageStream, mut backends: MessageStream,
    session: Arc<Mutex<Option<OwnedObjectPath>>>, alive: Arc<AtomicBool>, app: AppHandle) {
    struct InvalidateOnDrop(Arc<AtomicBool>);
    impl Drop for InvalidateOnDrop {
        fn drop(&mut self) { self.0.store(false, Ordering::Release); }
    }
    let _invalidate = InvalidateOnDrop(alive.clone());
    let closed = connection.closed();
    let mut closed = std::pin::pin!(closed);
    while alive.load(Ordering::Acquire) {
        let message = worker::wait_until(Instant::now() + Duration::from_secs(1), || {
            if alive.load(Ordering::Acquire) { Ok(()) } else { Err("portal_unavailable".into()) }
        }, poll_fn(|context| {
            if closed.as_mut().poll(context).is_ready() { return Poll::Ready(None); }
            if let Poll::Ready(message) = Pin::new(&mut owners).poll_next(context) { return Poll::Ready(message); }
            if let Poll::Ready(message) = Pin::new(&mut backends).poll_next(context) { return Poll::Ready(message); }
            Pin::new(&mut signals).poll_next(context)
        }));
        let message = match message {
            Err(code) if code == "portal_timeout" => continue,
            Ok(Some(Ok(message))) => message,
            _ => break,
        };
        let header = message.header();
        let interface = header.interface().map(|name| name.as_str());
        let member = header.member().map(|name| name.as_str());
        if interface == Some("org.freedesktop.DBus") && member == Some("NameOwnerChanged") {
            if let Ok((name, old, _new)) = message.body().deserialize::<(String, String, String)>() {
                if portal_owner_lost(&name, &old) { break; }
            }
        } else if interface == Some("org.freedesktop.portal.Session") && member == Some("Closed") {
            if session.lock().is_ok_and(|current| current.as_ref().is_some_and(|path| Some(path.as_str()) == header.path().map(|path| path.as_str()))) {
                break;
            }
        } else if interface == Some(INTERFACE) && member == Some("Activated") {
            let Ok((handle, id, _time, options)) = message.body()
                .deserialize::<(OwnedObjectPath, String, u64, HashMap<String, OwnedValue>)>() else { continue };
            if session.lock().map_or(true, |current| current.as_ref() != Some(&handle)) { continue; }
            let activation_token = options.get("activation_token")
                .and_then(|value| value.try_clone().ok()).and_then(|value| String::try_from(value).ok());
            let _ = app.emit_to("main", "portal-shortcut", Activation { id, activation_token });
        }
    }
    // Closed, owner loss, connection loss, and stream failure all invalidate cache.
    alive.store(false, Ordering::Release);
}

fn run(app: AppHandle, jobs: Arc<Jobs>) {
    let mut worker = Worker::<Portal>::default();
    loop {
        let job = jobs.next();
        worker.process(job, |operation| Portal::open(app.clone(), operation));
    }
}

/// Raises and focuses this process's window titled `caption` through KWin.
///
/// KDE's portal reports shortcut presses without an xdg-activation token, and
/// the token GTK then requests for itself is refused while another app (a
/// game) is active, so an already-open window would only demand attention.
/// KWin scripts may activate windows; the script matches our own PID only.
/// Best effort: other desktops have no KWin and keep the normal behaviour.
pub fn raise_with_kwin(caption: &'static str) {
    use zbus::blocking::{Connection, Proxy};
    static COUNTER: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
    std::thread::spawn(move || {
        let Some(runtime) = std::env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from).filter(|path| path.is_absolute())
        else {
            return;
        };
        let pid = std::process::id();
        let name = format!(
            "vrct_vox_raise_{pid}_{}",
            COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        );
        let path = runtime.join(format!("{name}.js"));
        let script = format!(
            "for (const w of workspace.windowList()) {{\n\
             \x20   if (w.pid === {pid} && w.caption === {caption:?}) {{ w.minimized = false; workspace.activeWindow = w; }}\n\
             }}\n"
        );
        let Ok(mut file) = std::fs::OpenOptions::new().write(true).create_new(true).open(&path) else { return };
        if std::io::Write::write_all(&mut file, script.as_bytes()).is_err() {
            let _ = std::fs::remove_file(&path);
            return;
        }
        drop(file);
        let run = || -> zbus::Result<()> {
            let connection = Connection::session()?;
            let scripting = Proxy::new(&connection, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting")?;
            let id: i32 = scripting.call("loadScript", &(path.to_string_lossy().as_ref(), name.as_str()))?;
            let loaded = Proxy::new(&connection, "org.kde.KWin", format!("/Scripting/Script{id}"), "org.kde.kwin.Script")
                .and_then(|script| script.call::<_, _, ()>("run", &()));
            // KWin evaluates the script asynchronously after run().
            std::thread::sleep(Duration::from_millis(500));
            let _: zbus::Result<bool> = scripting.call("unloadScript", &(name.as_str(),));
            loaded
        };
        let _ = run();
        let _ = std::fs::remove_file(&path);
    });
}

/// Binds exactly the given shortcuts (action id -> VRCT key list) and returns
/// the key the desktop assigned to each, which the user may have changed.
#[tauri::command]
pub async fn portal_shortcuts_bind(
    window: WebviewWindow,
    app: AppHandle,
    state: State<'_, PortalShortcuts>,
    shortcuts: HashMap<String, Vec<String>>,
) -> Result<HashMap<String, Assigned>, String> {
    if window.label() != "main" {
        return Err("portal_forbidden".into());
    }
    let mut binding = Binding::new();
    for (id, keys) in &shortcuts {
        if !ACTIONS.iter().any(|(action, _)| action == id) {
            return Err("portal_shortcut_unknown".into());
        }
        binding.push((id.clone(), trigger(keys).ok_or("portal_shortcut_invalid")?, qt_key(keys)));
    }
    binding.sort();
    let jobs = {
        let mut worker = state.0.lock().map_err(|_| "portal_unavailable")?;
        if worker.is_none() {
            let jobs = Arc::new(Jobs::default());
            let (app, receiver) = (app.clone(), jobs.clone());
            std::thread::Builder::new().name("vrct-portal-shortcuts".into())
                .spawn(move || run(app, receiver)).map_err(|_| "portal_unavailable")?;
            *worker = Some(jobs);
        }
        worker.as_ref().unwrap().clone()
    };
    let ticket = jobs.submit(binding, BIND_TIMEOUT);
    // Keep a cancellation guard in the command future, not in the detached
    // spawn_blocking task, so dropping the caller also abandons the operation.
    struct CancelOnDrop(Operation);
    impl Drop for CancelOnDrop { fn drop(&mut self) { self.0.cancel(); } }
    let _cancel = CancelOnDrop(ticket.operation.clone());
    tauri::async_runtime::spawn_blocking(move || ticket.receive()).await.map_err(|_| "portal_unavailable")?
}

#[cfg(test)]
mod tests {
    use super::*;

    fn keys(names: &[&str]) -> Vec<String> {
        names.iter().map(|name| (*name).to_owned()).collect()
    }

    #[test]
    fn converts_vrct_keys_to_portal_triggers() {
        assert_eq!(trigger(&keys(&["Ctrl", "Shift", "Q"])).as_deref(), Some("CTRL+SHIFT+q"));
        assert_eq!(trigger(&keys(&["Super", "Alt", "F2"])).as_deref(), Some("LOGO+ALT+F2"));
        assert_eq!(trigger(&keys(&["Ctrl", " "])).as_deref(), Some("CTRL+space"));
        assert_eq!(trigger(&keys(&["Ctrl", "1"])).as_deref(), Some("CTRL+1"));
        assert_eq!(trigger(&keys(&["Ctrl"])), None);
        assert_eq!(trigger(&keys(&["Ctrl", "A", "B"])), None);
        assert_eq!(trigger(&keys(&["Ctrl", "+"])), None);
    }

    #[test]
    fn converts_vrct_keys_to_kde_key_codes() {
        // Values as KDE stores them for Ctrl+Shift+Q and Ctrl+Alt+Q.
        assert_eq!(qt_key(&keys(&["Ctrl", "Shift", "Q"])), Some(100_663_377));
        assert_eq!(qt_key(&keys(&["Ctrl", "Alt", "Q"])), Some(201_326_673));
        assert_eq!(qt_key(&keys(&["Super", "F2"])), Some(QT_META | 0x0100_0031));
        assert_eq!(qt_key(&keys(&["Ctrl", " "])), Some(QT_CTRL | 0x20));
        assert_eq!(qt_key(&keys(&["Ctrl", "+"])), None);
        assert_eq!(qt_text(100_663_377), "Ctrl+Shift+Q");
        assert_eq!(qt_text(QT_META | QT_ALT | 0x0100_0031), "Meta+Alt+F2");
    }

    #[test]
    fn a_lost_or_replaced_portal_or_backend_ends_the_session() {
        assert!(portal_owner_lost(DESTINATION, ":1.48"));
        assert!(portal_owner_lost("org.freedesktop.impl.portal.desktop.kde", ":1.60"));
        assert!(portal_owner_lost("org.freedesktop.impl.portal.desktop.gnome", ":1.61"));
        // A name that appears for the first time took no session with it.
        assert!(!portal_owner_lost(DESTINATION, ""));
        assert!(!portal_owner_lost("org.freedesktop.impl.portal.desktop.kde", ""));
        assert!(!portal_owner_lost("org.freedesktop.impl.portal.desktopx", ":1.62"));
        assert!(!portal_owner_lost("org.kde.kglobalaccel", ":1.10"));
    }

    #[test]
    fn desktop_exec_is_quoted() {
        assert_eq!(quote("/opt/a b/$x\"y"), "\"/opt/a b/\\$x\\\"y\"");
    }
}
