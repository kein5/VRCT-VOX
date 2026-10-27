"""Validated, serializable P1 settings. New installations remain silent."""
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit


def local_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("A local HTTP server URL is required")
    url = urlsplit(value)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1")
            or url.username or url.password or url.query or url.fragment
            or url.path not in ("", "/")):
        raise ValueError("Use http://127.0.0.1:PORT (local server only)")
    port = url.port if url.port is not None else 80
    if not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    host = "[::1]" if url.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}"


# Explicit language selection; do not guess from a script or send auto to Irodori.
LANGUAGES = {
    "Japanese": "ja", "English": "en", "Chinese": "zh", "Korean": "ko",
    "Chinese Simplified": "zh", "Chinese Traditional": "zh",
    "German": "de", "French": "fr", "Russian": "ru", "Portuguese": "pt",
    "Spanish": "es", "Italian": "it",
}


def language_tag(language):
    if language in LANGUAGES.values():
        return language
    if language in LANGUAGES:
        return LANGUAGES[language]
    raise ValueError("Unsupported or unknown speech language")


@dataclass(frozen=True)
class VoiceSettings:
    mode: str = "off"  # off | original | translated (chat only)
    target_slot: str = "1"
    japanese_url: str = "http://127.0.0.1:8080"
    japanese_voice: str = "none"
    multilingual_url: str = ""
    multilingual_voice: str = "ryan"
    output_device: str = ""
    routing: str = "external"  # external | managed (Linux daemon-owned route)

    @property
    def playback_device(self):
        return "vrct.managed.tts" if self.routing == "managed" else self.output_device

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
            raise ValueError("Invalid voice settings")
        settings = cls(**value)
        if any(not isinstance(v, str) for v in asdict(settings).values()):
            raise ValueError("Voice settings must be strings")
        if settings.mode not in ("off", "original", "translated") or settings.target_slot not in ("1", "2", "3"):
            raise ValueError("Invalid speech mode or translation slot")
        if settings.routing not in ("external", "managed"):
            raise ValueError("Invalid routing mode")
        local_url(settings.japanese_url)
        if settings.multilingual_url:
            local_url(settings.multilingual_url)
        for voice in (settings.japanese_voice, settings.multilingual_voice):
            if not voice.strip() or len(voice) > 128 or any(ord(c) < 32 for c in voice):
                raise ValueError("Invalid voice name")
        if len(settings.output_device) > 512 or any(ord(c) < 32 for c in settings.output_device):
            raise ValueError("Invalid output device")
        if settings.mode != "off" and not settings.playback_device.strip():
            raise ValueError("Select a virtual microphone output before enabling TTS")
        return settings

    def to_dict(self):
        return asdict(self)

    def request_for(self, event):
        if self.mode == "translated":
            text, language = event.translated_text, event.target_language
        else:
            text, language = event.original_text, event.source_language
        if not text or not text.strip():
            raise ValueError("No text in the selected speech mode")
        language = language_tag(language)
        if language == "ja":
            return self.japanese_url, self.japanese_voice, language, text
        if not self.multilingual_url:
            raise ValueError("Configure a separate Qwen3-TTS server for this language")
        if local_url(self.multilingual_url) == local_url(self.japanese_url):
            raise ValueError("Japanese and multilingual TTS require separate servers")
        return self.multilingual_url, self.multilingual_voice, language, text


def normalize_settings(value, _instance=None):
    try:
        return VoiceSettings.from_dict(value).to_dict()
    except (ValueError, TypeError):
        return None
