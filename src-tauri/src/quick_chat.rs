//! One authenticated handoff to the main window's existing send hook.
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::sync::Mutex;
use tauri::{Emitter, Manager, State, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

#[derive(Clone, Deserialize, Serialize)]
pub struct Request {
    id: String,
    message: String,
}
#[derive(Clone, Serialize)]
pub struct Reply {
    id: String,
    accepted: bool,
}
#[derive(Clone, Deserialize, Serialize)]
pub struct Context {
    ready: bool,
    language: String,
    enter_to_send: bool,
    clear_on_send: bool,
}
impl Default for Context {
    fn default() -> Self {
        Self {
            ready: false,
            language: "en".into(),
            enter_to_send: true,
            clear_on_send: true,
        }
    }
}
#[derive(Default)]
struct Mailbox {
    context: Context,
    pending: Option<(Request, bool)>,
    completed: VecDeque<Reply>,
}
#[derive(Default)]
pub struct QuickChatState(Mutex<Mailbox>);
fn sender(label: &str, expected: &str) -> Result<(), String> {
    if label == expected {
        Ok(())
    } else {
        Err("quick_chat_forbidden".into())
    }
}
fn validate(label: &str, request: &Request) -> Result<(), String> {
    sender(label, "quick_chat")?;
    if request.id.is_empty()
        || request.id.len() > 64
        || !request
            .id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-')
    {
        return Err("quick_chat_invalid_request".into());
    }
    if request.message.trim().is_empty() {
        return Err("quick_chat_empty".into());
    }
    Ok(())
}
impl Mailbox {
    fn submit(&mut self, request: Request) -> Result<Option<Reply>, String> {
        if let Some(reply) = self.completed.iter().find(|r| r.id == request.id) {
            return Ok(Some(reply.clone()));
        }
        if let Some((pending, _)) = &self.pending {
            return if pending.id == request.id && pending.message == request.message {
                Ok(None)
            } else {
                Err("quick_chat_busy".into())
            };
        }
        if !self.context.ready {
            return Err("quick_chat_not_ready".into());
        }
        self.pending = Some((request, false));
        Ok(None)
    }
    fn take(&mut self) -> Option<Request> {
        let (request, taken) = self.pending.as_mut()?;
        if *taken {
            return None;
        }
        *taken = true;
        Some(request.clone())
    }
    fn finish(&mut self, id: &str, accepted: bool) -> Result<Reply, String> {
        if !self
            .pending
            .as_ref()
            .is_some_and(|(r, taken)| r.id == id && *taken)
        {
            return Err("quick_chat_invalid_request".into());
        }
        self.pending = None;
        let reply = Reply {
            id: id.into(),
            accepted,
        };
        self.completed.push_back(reply.clone());
        if self.completed.len() > 64 {
            self.completed.pop_front();
        }
        Ok(reply)
    }
}
#[tauri::command]
pub fn quick_chat_context(
    window: WebviewWindow,
    state: State<QuickChatState>,
) -> Result<Context, String> {
    sender(window.label(), "quick_chat")?;
    Ok(state
        .0
        .lock()
        .map_err(|_| "quick_chat_unavailable")?
        .context
        .clone())
}
#[tauri::command]
pub fn quick_chat_configure(
    window: WebviewWindow,
    state: State<QuickChatState>,
    context: Context,
) -> Result<(), String> {
    sender(window.label(), "main")?;
    if !["en", "ja", "ko", "zh-Hans", "zh-Hant"].contains(&context.language.as_str()) {
        return Err("quick_chat_invalid_language".into());
    }
    state
        .0
        .lock()
        .map_err(|_| "quick_chat_unavailable")?
        .context = context;
    Ok(())
}
#[tauri::command]
pub fn quick_chat_submit(
    window: WebviewWindow,
    state: State<QuickChatState>,
    request: Request,
) -> Result<Option<Reply>, String> {
    validate(window.label(), &request)?;
    let reply = state
        .0
        .lock()
        .map_err(|_| "quick_chat_unavailable")?
        .submit(request)?;
    if reply.is_none() {
        window
            .app_handle()
            .emit_to("main", "quick-chat-requested", ())
            .map_err(|e| e.to_string())?;
    }
    Ok(reply)
}
#[tauri::command]
pub fn quick_chat_take(
    window: WebviewWindow,
    state: State<QuickChatState>,
) -> Result<Option<Request>, String> {
    sender(window.label(), "main")?;
    Ok(state.0.lock().map_err(|_| "quick_chat_unavailable")?.take())
}
#[tauri::command]
pub fn quick_chat_finish(
    window: WebviewWindow,
    state: State<QuickChatState>,
    id: String,
    accepted: bool,
) -> Result<(), String> {
    sender(window.label(), "main")?;
    let reply = state
        .0
        .lock()
        .map_err(|_| "quick_chat_unavailable")?
        .finish(&id, accepted)?;
    window
        .app_handle()
        .emit_to("quick_chat", "quick-chat-result", reply)
        .map_err(|e| e.to_string())
}
#[tauri::command]
pub fn quick_chat_hide(window: WebviewWindow) -> Result<(), String> {
    sender(window.label(), "quick_chat")?;
    window.hide().map_err(|e| e.to_string())
}

#[cfg(target_os = "linux")]
async fn present_chat(chat: &WebviewWindow) -> Result<(), String> {
    use gtk::prelude::*;

    let (tx, mut rx) = tauri::async_runtime::channel(1);
    let target = chat.clone();
    chat.run_on_main_thread(move || {
        let result = (|| {
            let window = target.gtk_window().map_err(|e| e.to_string())?;
            window.realize();
            // Global shortcuts arrive outside GTK. CURRENT_TIME would reuse
            // GTK's previous input time, which KWin can reject as stale.
            let timestamp = window
                .window()
                .and_then(|native| native.downcast::<gdkx11::X11Window>().ok())
                .map(|native| {
                    // Required by get_server_time's property-notify roundtrip.
                    let gdk_window = native.upcast_ref::<gtk::gdk::Window>();
                    gdk_window.set_events(
                        gdk_window.events() | gtk::gdk::EventMask::PROPERTY_CHANGE_MASK,
                    );
                    gdkx11::functions::x11_get_server_time(&native)
                })
                .unwrap_or(gtk::gdk::ffi::GDK_CURRENT_TIME as u32);
            window.set_keep_above(true);
            window.show_all();
            window.deiconify();
            window.present_with_time(timestamp);
            Ok(())
        })();
        let _ = tx.try_send(result);
    })
    .map_err(|e| e.to_string())?;
    rx.recv().await.ok_or("quick_chat_unavailable")?
}

#[tauri::command]
pub async fn quick_chat_show(window: WebviewWindow, app: tauri::AppHandle) -> Result<(), String> {
    sender(window.label(), "main")?;
    let chat = if let Some(chat) = app.get_webview_window("quick_chat") {
        chat
    } else {
        WebviewWindowBuilder::new(
            &app,
            "quick_chat",
            WebviewUrl::App("quick-chat.html".into()),
        )
        .title("VRCT-VOX Quick Chat")
        .inner_size(480.0, 160.0)
        .min_inner_size(320.0, 120.0)
        .center()
        .skip_taskbar(true)
        .visible(false)
        .additional_browser_args(super::BROWSER_ARGS)
        .build()
        .map_err(|e| e.to_string())?
    };
    #[cfg(target_os = "linux")]
    present_chat(&chat).await?;
    #[cfg(not(target_os = "linux"))]
    {
        // Focus alone can leave the input behind a fullscreen/topmost game.
        // Apply this on every open, including reused hidden/minimized windows.
        chat.set_always_on_top(true).map_err(|e| e.to_string())?;
        chat.show().map_err(|e| e.to_string())?;
        chat.unminimize().map_err(|e| e.to_string())?;
        chat.set_focus().map_err(|e| e.to_string())?;
    }
    chat.emit("quick-chat-opened", ())
        .map_err(|e| e.to_string())
}
#[tauri::command]
pub fn quick_chat_shortcut_platform(window: WebviewWindow) -> Result<&'static str, String> {
    sender(window.label(), "main")?;
    if cfg!(target_os = "linux")
        && (std::env::var_os("WAYLAND_DISPLAY").is_some()
            || std::env::var("XDG_SESSION_TYPE").as_deref() == Ok("wayland"))
    {
        if std::env::var("GDK_BACKEND").as_deref() == Ok("x11") {
            Ok("xwayland")
        } else {
            Ok("wayland")
        }
    } else {
        Ok("native")
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn request() -> Request {
        Request {
            id: "test-1".into(),
            message: "こんにちは".into(),
        }
    }
    #[test]
    fn authenticated_input() {
        assert!(validate("main", &request()).is_err());
        assert!(validate("vr_panel", &request()).is_err());
        assert!(validate("quick_chat", &request()).is_ok());
        let mut r = request();
        r.message = " ".into();
        assert!(validate("quick_chat", &r).is_err());
        r.message = "長い文章".repeat(600);
        assert!(validate("quick_chat", &r).is_ok());
    }
    #[test]
    fn retries_deliver_once_and_replay_acknowledgement() {
        let mut queue = Mailbox::default();
        assert!(queue.submit(request()).is_err());
        queue.context.ready = true;
        assert!(queue.submit(request()).unwrap().is_none());
        assert!(queue.submit(request()).unwrap().is_none());
        assert!(queue.take().is_some());
        assert!(queue.take().is_none());
        let mut other = request();
        other.id = "other".into();
        assert!(queue.submit(other).is_err());
        assert!(queue.finish("spoof", true).is_err());
        assert!(queue.finish("test-1", true).unwrap().accepted);
        assert!(queue.submit(request()).unwrap().unwrap().accepted);
        assert!(queue.take().is_none());
    }
}
