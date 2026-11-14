//! The saved model choices. They never record that a server should be running.

use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value};

use crate::{codes, Code};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Profile {
    Japanese,
    Multilingual,
    Asr,
}

impl Profile {
    pub const ALL: [Profile; 3] = [Profile::Japanese, Profile::Multilingual, Profile::Asr];

    pub fn name(self) -> &'static str {
        match self {
            Profile::Japanese => "japanese",
            Profile::Multilingual => "multilingual",
            Profile::Asr => "asr",
        }
    }

    pub fn from_name(name: &str) -> Result<Profile, Code> {
        Profile::ALL.into_iter().find(|profile| profile.name() == name).ok_or(codes::PROFILE_INVALID)
    }

    pub(crate) fn index(self) -> usize {
        self as usize
    }
}

/// One profile's choices. `diarization_model` is optional and for `asr` only.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProfileSettings {
    pub model: String,
    pub vad_model: String,
    pub diarization_model: String,
    pub voice_file: String,
    pub device: String,
    pub low_latency: bool,
}

impl Default for ProfileSettings {
    fn default() -> Self {
        ProfileSettings {
            model: String::new(),
            vad_model: String::new(),
            diarization_model: String::new(),
            voice_file: String::new(),
            device: "auto".into(),
            low_latency: false,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Settings {
    profiles: [ProfileSettings; 3],
}

impl Settings {
    pub fn profile(&self, profile: Profile) -> &ProfileSettings {
        &self.profiles[profile.index()]
    }

    /// The form the settings file holds.
    pub fn to_json(&self) -> Value {
        let mut profiles = Map::new();
        for profile in Profile::ALL {
            let row = self.profile(profile);
            let mut item = Map::new();
            item.insert("model".into(), row.model.clone().into());
            item.insert("vad_model".into(), row.vad_model.clone().into());
            item.insert("diarization_model".into(), row.diarization_model.clone().into());
            item.insert("voice_file".into(), row.voice_file.clone().into());
            item.insert("device".into(), row.device.clone().into());
            item.insert("low_latency".into(), row.low_latency.into());
            profiles.insert(profile.name().into(), Value::Object(item));
        }
        let mut root = Map::new();
        root.insert("version".into(), 1.into());
        root.insert("profiles".into(), Value::Object(profiles));
        Value::Object(root)
    }
}

/// What a start passes to the server: the settings of one profile, files checked.
pub type StartOptions = ProfileSettings;

/// `auto`, `cpu`, `gpu`, or one of the names `speech devices` prints (Vulkan0..Vulkan99).
pub fn device_allowed(device: &str) -> bool {
    matches!(device, "auto" | "cpu" | "gpu") || is_named_gpu(device)
}

pub(crate) fn is_named_gpu(device: &str) -> bool {
    device
        .strip_prefix("Vulkan")
        .is_some_and(|digits| (1..=2).contains(&digits.len()) && digits.bytes().all(|byte| byte.is_ascii_digit()))
}

const KEYS: [&str; 6] = ["model", "vad_model", "diarization_model", "voice_file", "device", "low_latency"];

fn text(row: &Map<String, Value>, key: &str, default: &str) -> Result<String, Code> {
    match row.get(key) {
        None => Ok(default.to_owned()),
        Some(Value::String(value)) if value.chars().count() <= 4096 && !value.chars().any(|c| (c as u32) < 32) => {
            Ok(value.clone())
        }
        Some(_) => Err(codes::SETTINGS_INVALID),
    }
}

pub fn normalize_settings(value: &Value) -> Result<Settings, Code> {
    let invalid = codes::SETTINGS_INVALID;
    let root = value.as_object().ok_or(invalid)?;
    if root.keys().any(|key| key != "version" && key != "profiles") {
        return Err(invalid);
    }
    // An integer 1 only: `true` and `1.0` are other types.
    if let Some(version) = root.get("version") {
        if !(version.is_u64() && version.as_u64() == Some(1)) {
            return Err(invalid);
        }
    }
    let empty = Map::new();
    let given = match root.get("profiles") {
        None => &empty,
        Some(Value::Object(given)) => given,
        Some(_) => return Err(invalid),
    };
    if given.keys().any(|key| Profile::from_name(key).is_err()) {
        return Err(invalid);
    }
    let mut result = Settings::default();
    for profile in Profile::ALL {
        let row = match given.get(profile.name()) {
            None => &empty,
            Some(Value::Object(row)) => row,
            Some(_) => return Err(invalid),
        };
        if row.keys().any(|key| !KEYS.contains(&key.as_str())) {
            return Err(invalid);
        }
        let low_latency = match row.get("low_latency") {
            None => false,
            Some(Value::Bool(value)) => *value,
            Some(_) => return Err(invalid),
        };
        let item = ProfileSettings {
            model: text(row, "model", "")?,
            vad_model: text(row, "vad_model", "")?,
            diarization_model: text(row, "diarization_model", "")?,
            voice_file: text(row, "voice_file", "")?,
            device: text(row, "device", "auto")?,
            low_latency,
        };
        let misplaced = if profile == Profile::Asr {
            !item.voice_file.is_empty()
        } else {
            !item.vad_model.is_empty() || !item.diarization_model.is_empty()
        };
        if (low_latency && profile != Profile::Japanese) || !device_allowed(&item.device) || misplaced {
            return Err(invalid);
        }
        result.profiles[profile.index()] = item;
    }
    Ok(result)
}

fn expand_user(value: &str) -> PathBuf {
    if value == "~" || value.starts_with("~/") || (cfg!(windows) && value.starts_with("~\\")) {
        let home = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" });
        if let Some(home) = home.filter(|home| !home.is_empty()) {
            return Path::new(&home).join(value[1..].trim_start_matches(['/', '\\']));
        }
    }
    PathBuf::from(value)
}

/// The resolved path of an existing regular `.gguf` file that begins with the GGUF magic.
fn gguf(value: &str) -> Result<String, Code> {
    let checked = || -> Option<String> {
        if value.is_empty() {
            return None;
        }
        let path = std::fs::canonicalize(expand_user(value)).ok()?;
        let named = path.extension().is_some_and(|suffix| suffix.eq_ignore_ascii_case("gguf"));
        if !named || !path.metadata().ok()?.is_file() {
            return None;
        }
        let mut magic = [0u8; 4];
        File::open(&path).ok()?.read_exact(&mut magic).ok()?;
        if &magic != b"GGUF" {
            return None;
        }
        path.into_os_string().into_string().ok()
    };
    checked().ok_or(codes::MODEL_INVALID)
}

/// The options to start `profile` with, or the code of what is wrong with its files.
pub fn start_options(settings: &Value, profile: Profile) -> Result<StartOptions, Code> {
    let mut row = normalize_settings(settings)?.profile(profile).clone();
    row.model = gguf(&row.model)?;
    if profile == Profile::Asr {
        row.vad_model = gguf(&row.vad_model)?;
        if !row.diarization_model.is_empty() {
            row.diarization_model = gguf(&row.diarization_model)?;
        }
    } else if !row.voice_file.is_empty() {
        row.voice_file = gguf(&row.voice_file)?;
    }
    Ok(row)
}
