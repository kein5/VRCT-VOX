//! Linux: where the backend finds the VR UI's picture and sends its pointer.
//!
//! On Windows the VR page lives in a window parked off-screen, and the backend
//! photographs that window and posts mouse messages to it. A Wayland client can
//! neither place a window off-screen nor read another window, so here the page
//! is moved into a `GtkOffscreenWindow`: it never appears on the desktop, GTK
//! hands us every repaint, and synthetic GDK events reach WebKit like a mouse.
//!
//! The backend reads frames from `<dir>/frame` and writes one-line pointer
//! commands to the datagram socket `<dir>/input.sock`. `<dir>` is private to
//! this process and its children (`VRCT_VR_PANEL_DIR`).
use std::cell::{Cell, RefCell};
use std::fs::{DirBuilder, File, OpenOptions};
use std::os::unix::fs::{DirBuilderExt, FileExt, OpenOptionsExt};
use std::os::unix::net::UnixDatagram;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use gtk::prelude::*;
use gtk::{cairo, gdk, glib};
use webkit2gtk::{HardwareAccelerationPolicy, SettingsExt, WebViewExt};

pub const DIRECTORY_ENV: &str = "VRCT_VR_PANEL_DIR";
const MAGIC: &[u8; 8] = b"VRCTVRP1";
pub const HEADER_SIZE: usize = 64;
/// The atlas the page draws before the backend asks for another size
/// (`src-ui/views/vr/vr_layout.json`).
const DEFAULT_SIZE: (i32, i32) = (1628, 880);
const MAX_SIDE: i32 = 8192;
/// Copying a frame costs a few MB; the overlay does not show more than this.
const FRAME_INTERVAL: Duration = Duration::from_millis(33);
const STOP: &[u8] = b"stop";

/// One pointer command from the backend. Coordinates are page pixels.
#[derive(Debug, PartialEq)]
pub enum Command {
    Move { x: f64, y: f64, pressed: bool },
    Down { x: f64, y: f64 },
    Up { x: f64, y: f64 },
    /// `delta` in wheel notches, positive scrolls the page down.
    Wheel { x: f64, y: f64, delta: f64 },
    Resize { width: i32, height: i32 },
}

/// `move 10 20 1`, `down 10 20`, `up 10 20`, `wheel 10 20 -1.5`, `resize 1628 880`.
pub fn parse_command(text: &str) -> Option<Command> {
    let mut parts = text.split_ascii_whitespace();
    let kind = parts.next()?;
    let mut number = || parts.next()?.parse::<f64>().ok().filter(|value| value.is_finite());
    let command = match kind {
        "move" => Command::Move { x: number()?, y: number()?, pressed: number()? != 0.0 },
        "down" => Command::Down { x: number()?, y: number()? },
        "up" => Command::Up { x: number()?, y: number()? },
        "wheel" => Command::Wheel { x: number()?, y: number()?, delta: number()? },
        "resize" => {
            let (width, height) = (number()?, number()?);
            let valid = |side: f64| side.fract() == 0.0 && (1.0..=f64::from(MAX_SIDE)).contains(&side);
            if !valid(width) || !valid(height) {
                return None;
            }
            Command::Resize { width: width as i32, height: height as i32 }
        }
        _ => return None,
    };
    parts.next().is_none().then_some(command)
}

/// The fixed part of the frame file. `sequence` is odd while the pixels are
/// being replaced, so a reader that sees the same even number before and after
/// its copy has a whole frame. `instance` is 0 once the page is gone.
pub fn header(sequence: u64, instance: u64, width: u32, height: u32, stride: u32) -> [u8; HEADER_SIZE] {
    let mut bytes = [0u8; HEADER_SIZE];
    bytes[..8].copy_from_slice(MAGIC);
    bytes[8..16].copy_from_slice(&sequence.to_le_bytes());
    bytes[16..24].copy_from_slice(&instance.to_le_bytes());
    bytes[24..28].copy_from_slice(&width.to_le_bytes());
    bytes[28..32].copy_from_slice(&height.to_le_bytes());
    bytes[32..36].copy_from_slice(&stride.to_le_bytes());
    bytes
}

fn directory_for(runtime: &Path, process: u32) -> PathBuf {
    runtime.join("vrct-vox").join(format!("vr-panel-{process}"))
}

/// Directories of processes that no longer exist (a crash leaves one behind).
fn stale_directories(parent: &Path, alive: impl Fn(u32) -> bool) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(parent) else { return Vec::new() };
    entries
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let name = entry.file_name();
            let process = name.to_str()?.strip_prefix("vr-panel-")?.parse::<u32>().ok()?;
            (!alive(process)).then(|| entry.path())
        })
        .collect()
}

/// Chooses the private directory and tells the backend about it. Call before
/// the backend starts; without a runtime directory the VR UI stays unavailable.
pub fn prepare() -> Option<PathBuf> {
    // A value inherited from elsewhere would point the backend at someone else's files.
    std::env::remove_var(DIRECTORY_ENV);
    let runtime = std::env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from).filter(|path| path.is_absolute())?;
    let directory = directory_for(&runtime, std::process::id());
    let parent = directory.parent()?;
    DirBuilder::new().recursive(true).mode(0o700).create(parent).ok()?;
    for stale in stale_directories(parent, |process| Path::new(&format!("/proc/{process}")).exists()) {
        let _ = std::fs::remove_dir_all(stale);
    }
    let _ = std::fs::remove_dir_all(&directory);
    DirBuilder::new().mode(0o700).create(&directory).ok()?;
    std::env::set_var(DIRECTORY_ENV, &directory);
    Some(directory)
}

/// Removes the directory when the app ends.
pub fn cleanup() {
    if let Some(directory) = std::env::var_os(DIRECTORY_ENV) {
        let _ = std::fs::remove_dir_all(directory);
    }
}

struct Panel {
    offscreen: gtk::OffscreenWindow,
    view: webkit2gtk::WebView,
    file: File,
    frame_path: PathBuf,
    socket_path: PathBuf,
    image: Option<cairo::ImageSurface>,
    sequence: u64,
    instance: u64,
    pressed: bool,
    timer: Option<glib::SourceId>,
    stop: Arc<AtomicBool>,
}

thread_local! {
    // GTK objects stay on the main thread.
    static PANEL: RefCell<Option<Panel>> = const { RefCell::new(None) };
}

impl Panel {
    fn open(view: webkit2gtk::WebView, directory: &Path) -> Result<Self, String> {
        // An offscreen window has no GL surface, and WebKit aborts the whole app when a page
        // that composites on the GPU asks for one. The policy only binds a web process that
        // starts after it is set, and Tauri has already started loading the page, so end
        // that process and load the page again once it sits in the offscreen window.
        let address = view.uri();
        if let Some(settings) = WebViewExt::settings(&view) {
            settings.set_hardware_acceleration_policy(HardwareAccelerationPolicy::Never);
        }
        view.terminate_web_process();
        if let Some(parent) = view.parent().and_then(|parent| parent.downcast::<gtk::Container>().ok()) {
            parent.remove(&view);
        }
        let offscreen = gtk::OffscreenWindow::new();
        offscreen.set_default_size(DEFAULT_SIZE.0, DEFAULT_SIZE.1);
        view.set_size_request(DEFAULT_SIZE.0, DEFAULT_SIZE.1);
        offscreen.add(&view);
        offscreen.show_all();
        match address {
            Some(address) => view.load_uri(&address),
            None => view.reload(),
        }

        let frame_path = directory.join("frame");
        let socket_path = directory.join("input.sock");
        let _ = std::fs::remove_file(&frame_path);
        let _ = std::fs::remove_file(&socket_path);
        let file = OpenOptions::new().read(true).write(true).create_new(true).mode(0o600).open(&frame_path)
            .map_err(|error| format!("vr_panel_frame_failed: {error}"))?;
        // Never 0, and different for each page so the backend notices a new one.
        let instance = (u64::from(std::process::id()) << 32) | (glib::monotonic_time() as u64 & 0xFFFF_FFFF) | 1;
        file.write_all_at(&header(0, instance, 0, 0, 0), 0).map_err(|error| format!("vr_panel_frame_failed: {error}"))?;

        let socket = UnixDatagram::bind(&socket_path).map_err(|error| format!("vr_panel_input_failed: {error}"))?;
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = stop.clone();
        std::thread::Builder::new().name("vrct-vr-panel-input".into()).spawn(move || {
            let mut buffer = [0u8; 128];
            while let Ok(length) = socket.recv(&mut buffer) {
                if stopping.load(Ordering::Acquire) {
                    break;
                }
                let Some(command) = std::str::from_utf8(&buffer[..length]).ok().and_then(parse_command) else { continue };
                glib::MainContext::default().invoke(move || {
                    PANEL.with(|panel| {
                        if let Some(panel) = panel.borrow_mut().as_mut() {
                            panel.apply(command);
                        }
                    });
                });
            }
        }).map_err(|error| format!("vr_panel_input_failed: {error}"))?;

        let dirty = Rc::new(Cell::new(true));
        let damaged = dirty.clone();
        offscreen.connect_damage_event(move |_, _| {
            damaged.set(true);
            false
        });
        let timer = glib::timeout_add_local(FRAME_INTERVAL, move || {
            if dirty.replace(false) {
                PANEL.with(|panel| {
                    if let Some(panel) = panel.borrow_mut().as_mut() {
                        panel.publish();
                    }
                });
            }
            glib::ControlFlow::Continue
        });
        Ok(Self { offscreen, view, file, frame_path, socket_path, image: None, sequence: 0, instance, pressed: false,
            timer: Some(timer), stop })
    }

    /// Copies what GTK last painted into the frame file.
    fn publish(&mut self) {
        let Some(surface) = self.offscreen.surface() else { return };
        let (width, height) = (self.offscreen.allocated_width(), self.offscreen.allocated_height());
        if width <= 0 || height <= 0 || width > MAX_SIDE || height > MAX_SIDE {
            return;
        }
        if self.image.as_ref().is_none_or(|image| (image.width(), image.height()) != (width, height)) {
            self.image = cairo::ImageSurface::create(cairo::Format::ARgb32, width, height).ok();
        }
        let Some(image) = self.image.as_mut() else { return };
        {
            // Logical pixels on every display scale: the backend's layout counts in those.
            let Ok(context) = cairo::Context::new(&*image) else { return };
            context.set_operator(cairo::Operator::Source);
            if context.set_source_surface(&surface, 0.0, 0.0).is_err() || context.paint().is_err() {
                return;
            }
        }
        image.flush();
        let stride = image.stride() as u32;
        let Ok(data) = image.data() else { return };
        // Odd while the pixels change; readers retry.
        let writing = self.sequence + 1;
        if self.file.write_all_at(&writing.to_le_bytes(), 8).is_err() || self.file.write_all_at(&data, HEADER_SIZE as u64).is_err() {
            return;
        }
        self.sequence += 2;
        let _ = self.file.write_all_at(&header(self.sequence, self.instance, width as u32, height as u32, stride), 0);
    }

    fn apply(&mut self, command: Command) {
        match command {
            Command::Resize { width, height } => {
                self.view.set_size_request(width, height);
                self.offscreen.resize(width, height);
            }
            Command::Move { x, y, pressed } => {
                self.pressed = pressed;
                self.pointer(gdk::ffi::GDK_MOTION_NOTIFY, x, y, 0.0);
            }
            Command::Down { x, y } => {
                self.pointer(gdk::ffi::GDK_BUTTON_PRESS, x, y, 0.0);
                self.pressed = true;
            }
            Command::Up { x, y } => {
                self.pressed = true; // The release itself still carries the button.
                self.pointer(gdk::ffi::GDK_BUTTON_RELEASE, x, y, 0.0);
                self.pressed = false;
            }
            Command::Wheel { x, y, delta } => self.pointer(gdk::ffi::GDK_SCROLL, x, y, delta),
        }
    }

    /// Hands WebKit one pointer event the way GDK would for a real mouse.
    fn pointer(&self, kind: gdk::ffi::GdkEventType, x: f64, y: f64, delta: f64) {
        use glib::translate::ToGlibPtr;
        let Some(window) = self.view.window() else { return };
        let state = if self.pressed { gdk::ffi::GDK_BUTTON1_MASK } else { 0 };
        let time = (glib::monotonic_time() / 1000) as u32;
        let device = gdk::Display::default().and_then(|display| display.default_seat()).and_then(|seat| seat.pointer());
        // SAFETY: the event is created, filled and freed here on the GTK thread; it
        // owns the window reference it is given, and GTK copies what it keeps.
        unsafe {
            let event = gdk::ffi::gdk_event_new(kind);
            (*event).any.window = window.to_glib_full();
            (*event).any.send_event = 1;
            if let Some(device) = &device {
                gdk::ffi::gdk_event_set_device(event, device.to_glib_none().0);
            }
            match kind {
                gdk::ffi::GDK_MOTION_NOTIFY => {
                    let motion = &mut (*event).motion;
                    (motion.time, motion.x, motion.y, motion.x_root, motion.y_root, motion.state) = (time, x, y, x, y, state);
                }
                gdk::ffi::GDK_BUTTON_PRESS | gdk::ffi::GDK_BUTTON_RELEASE => {
                    let button = &mut (*event).button;
                    (button.time, button.x, button.y, button.x_root, button.y_root, button.state) = (time, x, y, x, y, state);
                    button.button = 1;
                }
                _ => {
                    let scroll = &mut (*event).scroll;
                    (scroll.time, scroll.x, scroll.y, scroll.x_root, scroll.y_root, scroll.state) = (time, x, y, x, y, state);
                    scroll.direction = gdk::ffi::GDK_SCROLL_SMOOTH;
                    scroll.delta_y = delta;
                }
            }
            gtk::ffi::gtk_main_do_event(event);
            gdk::ffi::gdk_event_free(event);
        }
    }

    fn close(mut self) {
        if let Some(timer) = self.timer.take() {
            timer.remove();
        }
        // Tell readers the page is gone before the file disappears.
        let _ = self.file.write_all_at(&header(self.sequence + 2, 0, 0, 0, 0), 0);
        let _ = std::fs::remove_file(&self.frame_path);
        self.stop.store(true, Ordering::Release);
        if let Ok(waker) = UnixDatagram::unbound() {
            let _ = waker.send_to(STOP, &self.socket_path);
        }
        let _ = std::fs::remove_file(&self.socket_path);
        // The web view belongs to Tauri, which destroys it with its window.
        self.offscreen.remove(&self.view);
        // SAFETY: nothing else holds the offscreen window.
        unsafe { self.offscreen.destroy() };
    }
}

/// Moves the VR page of `window` off the desktop and starts serving it. The
/// window itself must stay hidden.
pub async fn attach(window: &tauri::WebviewWindow) -> Result<(), String> {
    let directory = std::env::var_os(DIRECTORY_ENV).map(PathBuf::from).ok_or("vr_panel_surface_unavailable")?;
    let (sender, receiver) = std::sync::mpsc::channel();
    window.with_webview(move |webview| {
        let opened = PANEL.with(|panel| {
            if let Some(old) = panel.borrow_mut().take() {
                old.close();
            }
            Panel::open(webview.inner(), &directory).map(|opened| {
                *panel.borrow_mut() = Some(opened);
            })
        });
        let _ = sender.send(opened);
    }).map_err(|error| error.to_string())?;
    tauri::async_runtime::spawn_blocking(move || receiver.recv_timeout(Duration::from_secs(5)))
        .await
        .map_err(|error| error.to_string())?
        .map_err(|_| "vr_panel_surface_timeout".to_owned())?
}

/// Stops serving the page. Call before its window is destroyed.
pub async fn detach<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    let (sender, receiver) = std::sync::mpsc::channel();
    let dispatched = app.run_on_main_thread(move || {
        PANEL.with(|panel| {
            if let Some(panel) = panel.borrow_mut().take() {
                panel.close();
            }
        });
        let _ = sender.send(());
    });
    if dispatched.is_ok() {
        let _ = tauri::async_runtime::spawn_blocking(move || receiver.recv_timeout(Duration::from_secs(5))).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pointer_commands_are_one_line_each() {
        assert_eq!(parse_command("move 10 20.5 1"), Some(Command::Move { x: 10.0, y: 20.5, pressed: true }));
        assert_eq!(parse_command("move -5 -5 0"), Some(Command::Move { x: -5.0, y: -5.0, pressed: false }));
        assert_eq!(parse_command("down 1 2"), Some(Command::Down { x: 1.0, y: 2.0 }));
        assert_eq!(parse_command("up 1 2"), Some(Command::Up { x: 1.0, y: 2.0 }));
        assert_eq!(parse_command("wheel 3 4 -1.5"), Some(Command::Wheel { x: 3.0, y: 4.0, delta: -1.5 }));
        assert_eq!(parse_command("resize 1628 880"), Some(Command::Resize { width: 1628, height: 880 }));
    }

    #[test]
    fn anything_else_is_ignored() {
        for text in ["", "stop", "move 1 2", "down 1 2 3", "move a b 1", "move inf 0 0", "move nan 0 0",
            "resize 0 10", "resize 10 -1", "resize 10.5 10", "resize 9000 10", "click 1 2", "wheel 1 2"] {
            assert_eq!(parse_command(text), None, "{text:?}");
        }
    }

    #[test]
    fn the_header_has_a_fixed_layout() {
        let bytes = header(6, 0x0102_0304_0506_0708, 1628, 880, 6512);
        assert_eq!(&bytes[..8], b"VRCTVRP1");
        assert_eq!(u64::from_le_bytes(bytes[8..16].try_into().unwrap()), 6);
        assert_eq!(u64::from_le_bytes(bytes[16..24].try_into().unwrap()), 0x0102_0304_0506_0708);
        assert_eq!(u32::from_le_bytes(bytes[24..28].try_into().unwrap()), 1628);
        assert_eq!(u32::from_le_bytes(bytes[28..32].try_into().unwrap()), 880);
        assert_eq!(u32::from_le_bytes(bytes[32..36].try_into().unwrap()), 6512);
        assert!(bytes[36..].iter().all(|byte| *byte == 0));
    }

    #[test]
    fn only_directories_of_dead_processes_are_stale() {
        let parent = std::env::temp_dir().join(format!("vrct-vr-panel-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&parent);
        for name in ["vr-panel-10", "vr-panel-20", "vr-panel-x", "other"] {
            std::fs::create_dir_all(parent.join(name)).unwrap();
        }
        let stale = stale_directories(&parent, |process| process == 10);
        assert_eq!(stale, vec![parent.join("vr-panel-20")]);
        assert_eq!(directory_for(Path::new("/run/user/1000"), 42), Path::new("/run/user/1000/vrct-vox/vr-panel-42"));
        std::fs::remove_dir_all(&parent).unwrap();
    }
}
