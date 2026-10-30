"""Validated speech settings. Chat and microphone speech are separately opt-in."""
from dataclasses import asdict, dataclass
import re
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
    mic_mode: str = "off"  # off | translated (Realtime mic finals only)
    direct_policy: str = "suppress"  # suppress managed direct voice | mix explicitly
    target_slot: str = "1"
    japanese_server: str = "external"  # external | bundled
    japanese_url: str = "http://127.0.0.1:8080"
    japanese_voice: str = "none"
    multilingual_url: str = ""
    multilingual_voice: str = "ryan"
    multilingual_server: str = "external"
    japanese_seed: str = ""
    multilingual_seed: str = ""
    japanese_instructions: str = ""
    multilingual_instructions: str = ""
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
        for role in ('japanese', 'multilingual'):
            seed = getattr(settings, role + '_seed')
            if seed and (not re.fullmatch(r'[0-9]{1,16}', seed) or int(seed) > 9007199254740991):
                raise ValueError('Invalid seed')
            instruction = getattr(settings, role + '_instructions')
            if len(instruction) > 4000 or any((ord(c) < 32 and c not in '\r\n\t') or ord(c) == 127 for c in instruction):
                raise ValueError('Invalid instructions')
        if settings.mode not in ("off", "original", "translated") or settings.target_slot not in ("1", "2", "3"):
            raise ValueError("Invalid speech mode or translation slot")
        if settings.mic_mode not in ("off", "translated") or settings.direct_policy not in ("suppress", "mix"):
            raise ValueError("Invalid microphone speech mode or direct voice policy")
        if settings.routing not in ("external", "managed"):
            raise ValueError("Invalid routing mode")
        if any(value not in ("external", "bundled") for value in (settings.japanese_server, settings.multilingual_server)):
            raise ValueError("Invalid speech server selection")
        local_url(settings.japanese_url)
        if settings.multilingual_url:
            local_url(settings.multilingual_url)
        for voice in (settings.japanese_voice, settings.multilingual_voice):
            if not voice.strip() or len(voice) > 128 or any(ord(c) < 32 for c in voice):
                raise ValueError("Invalid voice name")
        if len(settings.output_device) > 512 or any(ord(c) < 32 for c in settings.output_device):
            raise ValueError("Invalid output device")
        if (settings.mode != "off" or settings.mic_mode != "off") and not settings.playback_device.strip():
            raise ValueError("Select a virtual microphone output before enabling TTS")
        if settings.mic_mode != "off" and settings.direct_policy == "suppress" and settings.routing != "managed":
            raise ValueError("Direct voice suppression requires managed routing")
        return settings

    def to_dict(self):
        return asdict(self)

    def options_for(self, language):
        role = 'japanese' if language_tag(language) == 'ja' else 'multilingual'
        options = {}
        seed = getattr(self, role + '_seed')
        if seed != '':
            options['seed'] = int(seed)
        instruction = getattr(self, role + '_instructions')
        if instruction.strip():
            options['instructions'] = instruction
        return options

    def request_for(self, event, *, resolve_server=None):
        if event.source == "mic":
            if self.mic_mode != "translated":
                raise ValueError("Microphone speech is disabled")
            text, language = event.translated_text, event.target_language
        elif self.mode == "translated":
            text, language = event.translated_text, event.target_language
        else:
            text, language = event.original_text, event.source_language
        if not text or not text.strip():
            raise ValueError("No text in the selected speech mode")
        language = language_tag(language)
        role = "japanese" if language == "ja" else "multilingual"
        if getattr(self, role + "_server") == "bundled":
            if resolve_server is None:
                raise ValueError("speech_server_not_ready")
            return local_url(resolve_server(role)), getattr(self, role + "_voice"), language, text
        if language == "ja":
            return self.japanese_url, self.japanese_voice, language, text
        if not self.multilingual_url:
            raise ValueError("Configure a separate Qwen3-TTS server for this language")
        if self.japanese_server == "external" and local_url(self.multilingual_url) == local_url(self.japanese_url):
            raise ValueError("Japanese and multilingual TTS require separate servers")
        return self.multilingual_url, self.multilingual_voice, language, text


def normalize_settings(value, _instance=None):
    try:
        return VoiceSettings.from_dict(value).to_dict()
    except (ValueError, TypeError):
        return None
