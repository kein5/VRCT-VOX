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
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, State, WebviewWindow};
use zbus::blocking::{Connection, Proxy};
use zbus::zvariant::{OwnedObjectPath, OwnedValue, Value};

/// Must match a desktop file the portal can find; see `ensure_desktop_file`.
const APP_ID: &str = "io.github.kein5.vrct-tts";
const DESTINATION: &str = "org.freedesktop.portal.Desktop";
const DESKTOP: &str = "/org/freedesktop/portal/desktop";
const INTERFACE: &str = "org.freedesktop.portal.GlobalShortcuts";
const MARKER: &str = "X-VRCT-VOX-Generated=true";
/// The desktop may show a confirmation dialog while binding.
const BIND_TIMEOUT: Duration = Duration::from_secs(180);
const ACTIONS: [(&str, &str); 5] = [
    ("open_quick_chat", "Open the quick chat window"),
    ("toggle_vrct_visibility", "Minimize or restore VRCT-VOX"),
    ("toggle_translation", "Turn translation on or off"),
    ("toggle_transcription_send", "Turn microphone input on or off"),
    ("toggle_transcription_receive", "Turn listening on or off"),
];

/// (action id, portal trigger, Qt key code for KDE when representable)
type Binding = Vec<(String, String, Option<i32>)>;
type Reply = mpsc::Sender<Result<HashMap<String, Assigned>, String>>;

/// The key the desktop actually uses for one action. `applied` is false when
/// the desktop kept another key (for example one taken by another app), and
/// unknown on desktops whose assignment cannot be read back.
#[derive(Clone, Serialize)]
pub struct Assigned {
    shown: String,
    applied: Option<bool>,
}

#[derive(Default)]
pub struct PortalShortcuts(Mutex<Option<mpsc::Sender<(Binding, Reply)>>>);

#[derive(Clone, Serialize)]
struct Activation {
    id: String,
    activation_token: Option<String>,
}

fn failure(code: &str) -> impl Fn(zbus::Error) -> String + '_ {
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
fn ensure_desktop_file() -> Result<(), String> {
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
    sender: String,
    counter: u32,
}

impl Portal {
    fn open() -> Result<Self, String> {
        ensure_desktop_file()?;
        let connection = Connection::session().map_err(failure("portal_unavailable"))?;
        connection
            .call_method(
                Some(DESTINATION),
                DESKTOP,
                Some("org.freedesktop.host.portal.Registry"),
                "Register",
                &(APP_ID, HashMap::<&str, Value>::new()),
            )
            .map_err(failure("portal_app_id_unavailable"))?;
        let version: u32 = Proxy::new(&connection, DESTINATION, DESKTOP, INTERFACE)
            .and_then(|proxy| proxy.get_property("version"))
            .map_err(failure("portal_shortcuts_unsupported"))?;
        if version < 1 {
            return Err("portal_shortcuts_unsupported".into());
        }
        let sender = connection
            .unique_name()
            .ok_or("portal_unavailable")?
            .trim_start_matches(':')
            .replace('.', "_");
        Ok(Self { connection, sender, counter: 0 })
    }

    fn token(&mut self) -> String {
        self.counter += 1;
        format!("vrct_vox_{}_{}", std::process::id(), self.counter)
    }

    /// Calls a request-returning method and waits for its `Response`,
    /// subscribing first so a fast response cannot be missed.
    fn request<B>(&mut self, method: &str, token: &str, body: &B) -> Result<HashMap<String, OwnedValue>, String>
    where
        B: serde::Serialize + zbus::zvariant::DynamicType,
    {
        let path = format!("{DESKTOP}/request/{}/{token}", self.sender);
        let request = Proxy::new(&self.connection, DESTINATION, path.as_str(), "org.freedesktop.portal.Request")
            .map_err(failure("portal_unavailable"))?;
        let mut responses = request.receive_signal("Response").map_err(failure("portal_unavailable"))?;
        let portal = Proxy::new(&self.connection, DESTINATION, DESKTOP, INTERFACE)
            .map_err(failure("portal_unavailable"))?;
        let _: OwnedObjectPath = portal.call(method, body).map_err(failure("portal_request_failed"))?;
        let message = responses.next().ok_or("portal_request_failed")?;
        let (code, results): (u32, HashMap<String, OwnedValue>) =
            message.body().deserialize().map_err(failure("portal_request_failed"))?;
        match code {
            0 => Ok(results),
            1 => Err("portal_cancelled".into()),
            _ => Err("portal_request_failed".into()),
        }
    }

    fn create_session(&mut self) -> Result<OwnedObjectPath, String> {
        let token = self.token();
        let session_token = self.token();
        let options = HashMap::from([
            ("handle_token", Value::from(token.as_str())),
            ("session_handle_token", Value::from(session_token.as_str())),
        ]);
        let results = self.request("CreateSession", &token, &(options,))?;
        let handle = match results.get("session_handle").map(|value| &**value) {
            Some(Value::Str(path)) => path.as_str().to_owned(),
            Some(Value::ObjectPath(path)) => path.as_str().to_owned(),
            _ => return Err("portal_request_failed".into()),
        };
        OwnedObjectPath::try_from(handle).map_err(|_| "portal_request_failed".into())
    }

    fn bind(&mut self, session: &OwnedObjectPath, binding: &Binding) -> Result<HashMap<String, Assigned>, String> {
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
        let results = self.request("BindShortcuts", &token, &(session, shortcuts, "", options))?;
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
        Ok(binding
            .iter()
            .map(|(id, _, qt)| {
                let assigned = qt.and_then(|key| self.apply_on_kde(id, key)).unwrap_or_else(|| Assigned {
                    shown: described.get(id).cloned().unwrap_or_default(),
                    applied: None,
                });
                (id.clone(), assigned)
            })
            .collect())
    }

    /// A portal's preferred trigger only seeds a new shortcut: KDE keeps the
    /// key chosen in its first dialog even after VRCT changes. Make VRCT's
    /// setting authoritative the way System Settings edits a shortcut, then
    /// read back what KDE kept (it refuses keys taken by other components).
    fn apply_on_kde(&self, id: &str, key: i32) -> Option<Assigned> {
        let description = ACTIONS.iter().find(|(action, _)| *action == id).map_or("", |(_, text)| *text);
        let action = [APP_ID, id, "VRCT-VOX", description];
        let accel = Proxy::new(&self.connection, "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel").ok()?;
        let first = |keys: Vec<(Vec<i32>,)>| keys.into_iter().next().and_then(|(codes,)| codes.into_iter().next());
        let mut current = first(accel.call("shortcutKeys", &(action.as_slice(),)).ok()?);
        if current != Some(key) {
            let _: () = accel
                .call("setForeignShortcutKeys", &(action.as_slice(), vec![(vec![key, 0, 0, 0],)]))
                .ok()?;
            current = first(accel.call("shortcutKeys", &(action.as_slice(),)).ok()?);
        }
        Some(Assigned {
            shown: current.filter(|code| *code != 0).map(qt_text).unwrap_or_default(),
            applied: Some(current == Some(key)),
        })
    }

    fn close(&self, session: &OwnedObjectPath) {
        let _ = self.connection.call_method(
            Some(DESTINATION),
            session.as_str(),
            Some("org.freedesktop.portal.Session"),
            "Close",
            &(),
        );
    }
}

fn listen(connection: Connection, session: Arc<Mutex<Option<OwnedObjectPath>>>, app: AppHandle) {
    let Ok(portal) = Proxy::new(&connection, DESTINATION, DESKTOP, INTERFACE) else { return };
    let Ok(signals) = portal.receive_signal("Activated") else { return };
    for message in signals {
        let Ok((handle, id, _time, options)) =
            message.body().deserialize::<(OwnedObjectPath, String, u64, HashMap<String, OwnedValue>)>()
        else {
            continue;
        };
        if session.lock().map_or(true, |current| current.as_ref() != Some(&handle)) {
            continue;
        }
        // Lets the window take focus despite the compositor's focus-stealing rules.
        let activation_token = options
            .get("activation_token")
            .and_then(|value| value.try_clone().ok())
            .and_then(|value| String::try_from(value).ok());
        let _ = app.emit_to("main", "portal-shortcut", Activation { id, activation_token });
    }
}

fn run(app: AppHandle, jobs: mpsc::Receiver<(Binding, Reply)>) {
    let mut portal = match Portal::open() {
        Ok(portal) => portal,
        Err(code) => {
            for (_, reply) in jobs {
                let _ = reply.send(Err(code.clone()));
            }
            return;
        }
    };
    let session = Arc::new(Mutex::new(None::<OwnedObjectPath>));
    let (connection, current) = (portal.connection.clone(), session.clone());
    std::thread::spawn(move || listen(connection, current, app));
    let mut bound: Option<(Binding, HashMap<String, Assigned>)> = None;
    for (binding, reply) in jobs {
        if let Some((previous, shown)) = &bound {
            if *previous == binding {
                let _ = reply.send(Ok(shown.clone()));
                continue;
            }
        }
        // A session's shortcuts are fixed once bound: replace the session.
        if let Some(old) = session.lock().ok().and_then(|mut current| current.take()) {
            portal.close(&old);
        }
        bound = None;
        let result = if binding.is_empty() {
            Ok(HashMap::new())
        } else {
            portal.create_session().and_then(|handle| {
                if let Ok(mut current) = session.lock() {
                    *current = Some(handle.clone());
                }
                portal.bind(&handle, &binding)
            })
        };
        if let Ok(shown) = &result {
            bound = Some((binding, shown.clone()));
        }
        let _ = reply.send(result);
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
        worker
            .get_or_insert_with(|| {
                let (sender, receiver) = mpsc::channel();
                let app = app.clone();
                std::thread::Builder::new()
                    .name("vrct-portal-shortcuts".into())
                    .spawn(move || run(app, receiver))
                    .ok();
                sender
            })
            .clone()
    };
    let (reply, result) = mpsc::channel();
    jobs.send((binding, reply)).map_err(|_| "portal_unavailable")?;
    tauri::async_runtime::spawn_blocking(move || result.recv_timeout(BIND_TIMEOUT))
        .await
        .map_err(|_| "portal_unavailable")?
        .map_err(|_| "portal_timeout")?
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
    fn desktop_exec_is_quoted() {
        assert_eq!(quote("/opt/a b/$x\"y"), "\"/opt/a b/\\$x\\\"y\"");
    }
}
