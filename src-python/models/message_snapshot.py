"""Immutable content settings shared by every stage of an admitted message."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def language_payload(languages):
    # Wire/render consumers receive ordinary dictionaries, never live config.
    return {slot: dict(language) for slot, language in languages.items()}


@dataclass(frozen=True)
class MessageSnapshot:
    tab: str
    source_language: str
    your_languages: Mapping
    target_languages: Mapping
    translation_enabled: bool
    engine: str
    weight_type: str
    hiragana: bool
    romaji: bool
    send_only_translated: bool
    overlay_only_translated: bool
    format_parts: Mapping
    multi_target: bool

    @classmethod
    def capture(cls, config, spec, language):
        tab = config.SELECTED_TAB_NO
        your = freeze(config.SELECTED_YOUR_LANGUAGES[tab])
        target = freeze(config.SELECTED_TARGET_LANGUAGES[tab])
        source = your if spec.multi_target else target
        return cls(
            tab, language or source["1"]["language"], your, target,
            config.ENABLE_TRANSLATION, config.SELECTED_TRANSLATION_ENGINES[tab],
            config.CTRANSLATE2_WEIGHT_TYPE,
            config.CONVERT_MESSAGE_TO_HIRAGANA, config.CONVERT_MESSAGE_TO_ROMAJI,
            config.SEND_ONLY_TRANSLATED_MESSAGES, config.OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES,
            freeze(config.SEND_MESSAGE_FORMAT_PARTS if spec.osc_format_type == "SEND"
                   else config.RECEIVED_MESSAGE_FORMAT_PARTS), spec.multi_target,
        )

    @property
    def destinations(self):
        return self.target_languages if self.multi_target else self.your_languages

    @property
    def target_slots(self):
        return tuple(slot for slot, target in self.destinations.items() if target["enable"])
