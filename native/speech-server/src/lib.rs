//! Owns the bundled speech.cpp server processes: start, stop, restart and liveness.
//!
//! The behaviour follows `src-python/models/speech_server/`, which this crate is to
//! replace (issue #276): the same settings file, the same states and the same fixed
//! error codes. The speech.cpp executable stays a separate process; only the layer
//! that owns it lives here.
//!
//! Nothing in this crate logs or returns what the server prints, a model path, text
//! or audio. A failure is one of the fixed codes in [`codes`].

mod child;
mod http;

pub mod bundle;
pub mod devices;
pub mod server;
pub mod servers;
pub mod settings;
pub mod standby;
pub mod warmup;

pub use server::{Health, Hooks, SpeechServer, State};
pub use servers::SpeechServers;
pub use settings::{Profile, StartOptions};

/// A fixed error code. The app maps it to a message; it never carries detail.
pub type Code = &'static str;

/// The codes this crate reports, the same strings the Python layer used.
pub mod codes {
    pub const BUNDLE: &str = "speech_bundle_missing_or_invalid";
    pub const SETTINGS_INVALID: &str = "speech_server_settings_invalid";
    pub const MODEL_INVALID: &str = "speech_server_model_invalid";
    pub const PROFILE_INVALID: &str = "speech_server_profile_invalid";
    pub const SINGLE_USE: &str = "speech_server_single_use";
    pub const START_TIMEOUT: &str = "speech_server_start_timeout";
    pub const READINESS: &str = "speech_server_readiness";
    pub const MODEL_TASKS: &str = "speech_server_model_tasks";
    pub const PROTOCOL: &str = "speech_server_protocol";
    pub const EXITED: &str = "speech_server_exited";
    pub const OUT_OF_MEMORY: &str = "speech_server_out_of_memory";
    pub const DEVICE_FAILED: &str = "speech_server_device_failed";
    pub const VULKAN_MISSING: &str = "speech_server_vulkan_missing";
    pub const LAUNCH_FAILED: &str = "speech_server_launch_failed";
    pub const CLEANUP_UNCONFIRMED: &str = "speech_server_cleanup_unconfirmed";
    pub const NOTIFICATION_FAILED: &str = "speech_server_notification_failed";
    pub const LOW_LATENCY_REQUIRES_GPU_IRODORI: &str = "speech_server_low_latency_requires_gpu_irodori";
    pub const LOW_LATENCY_FAILED: &str = "speech_server_low_latency_failed";
    pub const NOT_READY: &str = "speech_server_not_ready";
    pub const CLOSED: &str = "speech_server_closed";
    pub const STALE_START: &str = "speech_server_stale_start";
    pub const BUSY: &str = "speech_server_busy";
}
