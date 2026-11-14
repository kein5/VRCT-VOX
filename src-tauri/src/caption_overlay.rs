//! Captions over the desktop, for VRChat without a headset.
//!
//! A second window stays above the other windows, lets every click through and
//! never takes the focus, so the game under it keeps its input. The main window
//! decides what it shows: it hands a snapshot to this module, and the overlay
//! page reads it back through a command that checks its label. Events carry no
//! data, as with the quick chat window.
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{
    Emitter, Manager, PhysicalPosition, PhysicalSize, State, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder,
};

pub const LABEL: &str = "caption_overlay";
const TITLE: &str = "VRCT-VOX Captions";
const MAX_LINES: usize = 8;
const MAX_TEXT: usize = 2000;
const MAX_TRANSLATIONS: usize = 3;
const MAX_SPEAKERS: usize = 4;
/// The band the captions are drawn in, as parts of the monitor's work area.
const BAND_WIDTH: f64 = 0.8;
const BAND_HEIGHT: f64 = 0.34;
const BAND_MARGIN: f64 = 0.03;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct Line {
    id: String,
    /// "sent" for the user's own words, "received" for what was heard or read.
    kind: String,
    text: String,
    #[serde(default)]
    translations: Vec<String>,
    /// Still being recognized or sent: the line stays until it settles.
    #[serde(default)]
    pending: bool,
    /// Who spoke a received line, where the voices were told apart: labels such as "A" and
    /// "B", in the order they speak. A label is a voice within one session, not a person.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    speakers: Vec<String>,
    /// Milliseconds since the epoch after which the line is no longer shown.
    until: f64,
}

/// One to three capital letters, as the speech server labels a voice.
fn valid_speaker(label: &str) -> bool {
    (1..=3).contains(&label.len()) && label.bytes().all(|byte| byte.is_ascii_uppercase())
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct Snapshot {
    lines: Vec<Line>,
    /// "bottom" or "top" of the monitor.
    position: String,
    font_size: u16,
    /// How dark the plate behind the words is, 0 to 1.
    opacity: f32,
    font_family: String,
}

impl Default for Snapshot {
    fn default() -> Self {
        Self {
            lines: Vec::new(),
            position: "bottom".into(),
            font_size: 28,
            opacity: 0.6,
            font_family: "Yu Gothic UI".into(),
        }
    }
}

#[derive(Default)]
pub struct CaptionOverlayState(Mutex<Snapshot>);

fn sender(label: &str, expected: &str) -> Result<(), String> {
    if label == expected {
        Ok(())
    } else {
        Err("caption_overlay_forbidden".into())
    }
}

fn valid_position(position: &str) -> Result<(), String> {
    if matches!(position, "bottom" | "top") {
        Ok(())
    } else {
        Err("caption_overlay_invalid".into())
    }
}

fn validate(snapshot: &Snapshot) -> Result<(), String> {
    let invalid = || Err("caption_overlay_invalid".to_string());
    valid_position(&snapshot.position)?;
    if !(16..=72).contains(&snapshot.font_size)
        || !(0.0..=1.0).contains(&snapshot.opacity)
        || snapshot.font_family.trim().is_empty()
        || snapshot.font_family.chars().count() > 256
        || snapshot.font_family.chars().any(char::is_control)
        || snapshot.lines.len() > MAX_LINES
    {
        return invalid();
    }
    for line in &snapshot.lines {
        if line.id.is_empty()
            || line.id.len() > 512
            || !matches!(line.kind.as_str(), "sent" | "received")
            || line.text.chars().count() > MAX_TEXT
            || line.translations.len() > MAX_TRANSLATIONS
            || line.translations.iter().any(|text| text.chars().count() > MAX_TEXT)
            || line.speakers.len() > MAX_SPEAKERS
            || !line.speakers.iter().all(|label| valid_speaker(label))
            // Only what was heard has several voices; the user's own line names no one.
            || (line.kind == "sent" && !line.speakers.is_empty())
            || !line.until.is_finite()
            || line.until < 0.0
        {
            return invalid();
        }
    }
    Ok(())
}

/// Where the band goes inside a work area of `(x, y, width, height)` physical pixels.
fn band(work: (i32, i32, u32, u32), position: &str) -> (i32, i32, u32, u32) {
    let (x, y, width, height) = work;
    let band_width = (f64::from(width) * BAND_WIDTH).round().max(1.0);
    let band_height = (f64::from(height) * BAND_HEIGHT).round().max(1.0);
    let margin = (f64::from(height) * BAND_MARGIN).round();
    let left = f64::from(x) + (f64::from(width) - band_width) / 2.0;
    let top = if position == "top" {
        f64::from(y) + margin
    } else {
        f64::from(y) + f64::from(height) - band_height - margin
    };
    (left.round() as i32, top.round() as i32, band_width as u32, band_height as u32)
}

/// Shows the window without making it the foreground window. Tauri's `show()`
/// activates it, which takes the keyboard from the game the captions are over.
#[cfg(windows)]
fn show_without_focus(overlay: &WebviewWindow) -> Result<(), String> {
    #[link(name = "user32")]
    extern "system" {
        fn ShowWindow(window: *mut std::ffi::c_void, command: i32) -> i32;
    }
    const SW_SHOWNOACTIVATE: i32 = 4;
    let handle = overlay.hwnd().map_err(|error| error.to_string())?;
    // SAFETY: the handle is this process's own live window, and ShowWindow has
    // no other precondition; its return value is the previous visibility.
    unsafe { ShowWindow(handle.0 as *mut std::ffi::c_void, SW_SHOWNOACTIVATE) };
    Ok(())
}

/// Linux, on X11 or XWayland: the window is mapped as an unmanaged (override-redirect)
/// window. A window manager stacks a focused full-screen game above "keep above"
/// windows (KWin's active layer), so a managed window would vanish under VRChat in
/// full screen. An unmanaged window is never focused, decorated or listed, and
/// KWin keeps it above managed windows, as it does tooltips and menus.
#[cfg(target_os = "linux")]
async fn on_gtk<F>(overlay: &WebviewWindow, work: F) -> Result<(), String>
where
    F: FnOnce(&gtk::ApplicationWindow) -> Result<(), String> + Send + 'static,
{
    let (tx, mut rx) = tauri::async_runtime::channel(1);
    let target = overlay.clone();
    overlay
        .run_on_main_thread(move || {
            let result = target.gtk_window().map_err(|error| error.to_string()).and_then(|window| work(&window));
            let _ = tx.try_send(result);
        })
        .map_err(|error| error.to_string())?;
    rx.recv().await.ok_or("caption_overlay_unavailable")?
}

/// Before any setting that needs the native window: tao's click-through request
/// unwraps the GdkWindow and panics while the window is not realized (seen on the
/// first open in CI). Realizing does not map it, so override-redirect still applies.
#[cfg(target_os = "linux")]
async fn prepare(overlay: &WebviewWindow) -> Result<(), String> {
    use gtk::prelude::*;

    on_gtk(overlay, |window| {
        window.realize();
        let native = window.window().ok_or("caption_overlay_unavailable")?;
        if !native.is_visible() {
            // X11 takes this attribute only while the window is unmapped.
            native.set_override_redirect(true);
        }
        window.set_accept_focus(false);
        window.set_focus_on_map(false);
        Ok(())
    })
    .await
}

#[cfg(target_os = "linux")]
async fn show_without_focus(overlay: &WebviewWindow) -> Result<(), String> {
    use gtk::prelude::*;

    on_gtk(overlay, |window| {
        window.show_all();
        if let Some(native) = window.window() {
            native.raise();
        }
        Ok(())
    })
    .await
}

/// Keeps the unmanaged window on top. Under a plain X11 window manager a game raised
/// later can cover it; KWin needs nothing here. Raising never takes the focus.
#[cfg(target_os = "linux")]
fn raise(overlay: &WebviewWindow) {
    use gtk::prelude::*;

    let target = overlay.clone();
    let _ = overlay.run_on_main_thread(move || {
        if let Ok(window) = target.gtk_window() {
            if let Some(native) = window.window() {
                native.raise();
            }
            // A transparent X11 surface may stay unpainted until it is drawn again.
            window.queue_draw();
        }
    });
}

#[cfg(not(any(windows, target_os = "linux")))]
fn show_without_focus(overlay: &WebviewWindow) -> Result<(), String> {
    overlay.show().map_err(|error| error.to_string())
}

/// Windows, and Linux where GTK draws on X11 (the AppImage, which uses XWayland on
/// a Wayland desktop). Native Wayland gives a client no window that stays above a
/// full-screen game; the layer-shell protocol would, and is not used yet.
fn platform_supported() -> bool {
    #[cfg(target_os = "linux")]
    {
        !crate::quick_chat::native_wayland()
    }
    #[cfg(not(target_os = "linux"))]
    {
        cfg!(windows)
    }
}

#[tauri::command]
pub fn caption_overlay_supported(window: WebviewWindow) -> Result<bool, String> {
    sender(window.label(), "main")?;
    Ok(platform_supported())
}

// One open or close at a time: a close that has not finished must not look
// like an existing window to the next open (see set_vr_panel_window).
static LOCK: tauri::async_runtime::Mutex<()> = tauri::async_runtime::Mutex::const_new(());

/// Shows the overlay on the monitor the main window is on, or removes it.
#[tauri::command]
pub async fn caption_overlay_set(
    window: WebviewWindow,
    app: tauri::AppHandle,
    open: bool,
    position: String,
) -> Result<(), String> {
    sender(window.label(), "main")?;
    valid_position(&position)?;
    let _guard = LOCK.lock().await;
    let existing = app.get_webview_window(LABEL);
    if !open {
        if let Some(overlay) = existing {
            overlay.destroy().map_err(|error| error.to_string())?;
            for _ in 0..40 {
                if app.get_webview_window(LABEL).is_none() {
                    break;
                }
                tauri::async_runtime::spawn_blocking(|| {
                    std::thread::sleep(std::time::Duration::from_millis(50))
                })
                .await
                .map_err(|error| error.to_string())?;
            }
        }
        return Ok(());
    }
    if !platform_supported() {
        return Err("caption_overlay_unsupported".into());
    }
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .or(window.primary_monitor().map_err(|error| error.to_string())?)
        .ok_or("caption_overlay_no_monitor")?;
    let work = monitor.work_area();
    let (x, y, width, height) = band(
        (work.position.x, work.position.y, work.size.width, work.size.height),
        &position,
    );
    let overlay = match existing {
        Some(overlay) => overlay,
        None => WebviewWindowBuilder::new(&app, LABEL, WebviewUrl::App("caption-overlay.html".into()))
            .title(TITLE)
            .decorations(false)
            .transparent(true)
            .shadow(false)
            .resizable(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .focused(false)
            .focusable(false)
            .visible(false)
            .additional_browser_args(super::BROWSER_ARGS)
            .build()
            .map_err(|error| error.to_string())?,
    };
    #[cfg(target_os = "linux")]
    prepare(&overlay).await?;
    overlay.set_ignore_cursor_events(true).map_err(|error| error.to_string())?;
    overlay.set_position(PhysicalPosition::new(x, y)).map_err(|error| error.to_string())?;
    overlay.set_size(PhysicalSize::new(width, height)).map_err(|error| error.to_string())?;
    overlay.set_always_on_top(true).map_err(|error| error.to_string())?;
    #[cfg(target_os = "linux")]
    {
        show_without_focus(&overlay).await
    }
    #[cfg(not(target_os = "linux"))]
    {
        show_without_focus(&overlay)
    }
}

/// The main window hands over what to draw.
#[tauri::command]
pub fn caption_overlay_update(
    window: WebviewWindow,
    state: State<CaptionOverlayState>,
    snapshot: Snapshot,
) -> Result<(), String> {
    sender(window.label(), "main")?;
    validate(&snapshot)?;
    *state.0.lock().map_err(|_| "caption_overlay_unavailable")? = snapshot;
    // No overlay window yet is not an error: it reads the snapshot when it opens.
    let _ = window.app_handle().emit_to(LABEL, "caption-overlay-changed", ());
    #[cfg(target_os = "linux")]
    if let Some(overlay) = window.app_handle().get_webview_window(LABEL) {
        raise(&overlay);
    }
    Ok(())
}

/// The overlay page reads what to draw.
#[tauri::command]
pub fn caption_overlay_snapshot(
    window: WebviewWindow,
    state: State<CaptionOverlayState>,
) -> Result<Snapshot, String> {
    sender(window.label(), LABEL)?;
    Ok(state.0.lock().map_err(|_| "caption_overlay_unavailable")?.clone())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn line() -> Line {
        Line {
            id: "realtime:mic:1:session:item".into(),
            kind: "sent".into(),
            text: "こんにちは".into(),
            translations: vec!["Hello".into()],
            pending: false,
            speakers: Vec::new(),
            until: 1_800_000_000_000.0,
        }
    }

    fn heard(speakers: &[&str]) -> Snapshot {
        let mut value = snapshot();
        value.lines[0].kind = "received".into();
        value.lines[0].speakers = speakers.iter().map(|label| label.to_string()).collect();
        value
    }

    #[test]
    fn a_heard_line_may_name_up_to_four_voices_by_short_capital_labels() {
        for speakers in [vec![], vec!["A"], vec!["C", "B"], vec!["A", "B", "C", "AB"], vec!["ABC"]] {
            let value = heard(&speakers);
            assert!(validate(&value).is_ok(), "{speakers:?}");
            let copy: Snapshot = serde_json::from_value(serde_json::to_value(&value).unwrap()).unwrap();
            assert_eq!(copy, value);
        }
        // A line without speakers is written as before, so an older overlay page reads it.
        assert!(serde_json::to_value(heard(&[])).unwrap()["lines"][0].get("speakers").is_none());
        for speakers in [vec!["a"], vec![""], vec!["ABCD"], vec!["A1"], vec!["あ"], vec!["A", "B", "C", "D", "E"]] {
            assert_eq!(validate(&heard(&speakers)), Err("caption_overlay_invalid".into()), "{speakers:?}");
        }
        // The user's own words are one voice: a sent line that names speakers is refused.
        let mut own = heard(&["A"]);
        own.lines[0].kind = "sent".into();
        assert_eq!(validate(&own), Err("caption_overlay_invalid".into()));
    }

    fn snapshot() -> Snapshot {
        Snapshot { lines: vec![line()], ..Snapshot::default() }
    }

    #[test]
    fn only_the_main_window_writes_and_only_the_overlay_reads() {
        assert!(sender("main", "main").is_ok());
        assert!(sender(LABEL, LABEL).is_ok());
        for label in ["quick_chat", "vr_panel", LABEL, "unknown"] {
            assert_eq!(sender(label, "main"), Err("caption_overlay_forbidden".into()));
        }
        for label in ["main", "quick_chat", "vr_panel"] {
            assert_eq!(sender(label, LABEL), Err("caption_overlay_forbidden".into()));
        }
    }

    #[test]
    fn a_snapshot_roundtrips_and_old_lines_default_their_optional_fields() {
        let copy: Snapshot = serde_json::from_value(serde_json::to_value(snapshot()).unwrap()).unwrap();
        assert_eq!(copy, snapshot());
        let legacy = serde_json::json!({ "id": "a", "kind": "received", "text": "hi", "until": 5.0 });
        let line: Line = serde_json::from_value(legacy).unwrap();
        assert!(line.translations.is_empty() && !line.pending);
        assert!(validate(&snapshot()).is_ok());
        assert!(validate(&Snapshot::default()).is_ok());
    }

    #[test]
    fn a_snapshot_out_of_bounds_is_refused() {
        let cases: Vec<Box<dyn Fn(&mut Snapshot)>> = vec![
            Box::new(|s| s.position = "left".into()),
            Box::new(|s| s.font_size = 15),
            Box::new(|s| s.font_size = 73),
            Box::new(|s| s.opacity = 1.5),
            Box::new(|s| s.opacity = f32::NAN),
            Box::new(|s| s.font_family = " ".into()),
            Box::new(|s| s.font_family = "a\nb".into()),
            Box::new(|s| s.lines = vec![line(); MAX_LINES + 1]),
            Box::new(|s| s.lines[0].id.clear()),
            Box::new(|s| s.lines[0].kind = "system".into()),
            Box::new(|s| s.lines[0].text = "あ".repeat(MAX_TEXT + 1)),
            Box::new(|s| s.lines[0].translations = vec!["a".into(); MAX_TRANSLATIONS + 1]),
            Box::new(|s| s.lines[0].until = f64::INFINITY),
            Box::new(|s| s.lines[0].until = -1.0),
        ];
        for change in cases {
            let mut value = snapshot();
            change(&mut value);
            assert_eq!(validate(&value), Err("caption_overlay_invalid".into()));
        }
        // Long Japanese text is counted in characters, not bytes.
        let mut long = snapshot();
        long.lines[0].text = "あ".repeat(MAX_TEXT);
        assert!(validate(&long).is_ok());
    }

    #[test]
    fn the_band_is_centred_and_stays_inside_the_work_area() {
        // A 1920x1080 monitor with a 48px taskbar at the bottom.
        let work = (0, 0, 1920, 1032);
        let (x, y, width, height) = band(work, "bottom");
        assert_eq!((x, width), (192, 1536));
        assert_eq!(height, 351);
        assert_eq!(y + height as i32, 1032 - 31);
        let (_, top, _, _) = band(work, "top");
        assert_eq!(top, 31);
        // A second monitor above the first one has a negative origin.
        let (x, y, width, height) = band((-1920, -1080, 1920, 1080), "bottom");
        assert!(x >= -1920 && x + width as i32 <= 0);
        assert!(y >= -1080 && y + height as i32 <= 0);
    }
}
