"""Translate existing pipeline values without changing legacy payloads."""
from uuid import uuid4

from models.voice_events import SpeechMessageEvent


def chat_event(message, translations, *, event_id, started_ns, source_language,
               targets, target_slots, selected_slot):
    translated_text = None
    target_language = None
    if selected_slot in target_slots:
        index = target_slots.index(selected_slot)
        target = targets[selected_slot]
        if target.get("enable") is True and index < len(translations):
            translated_text = translations[index]
            target_language = target.get("language")
    return SpeechMessageEvent(
        event_id=str(event_id) if event_id is not None else str(uuid4()), source="chat",
        original_text=message, translated_text=translated_text,
        source_language=source_language, target_language=target_language, timestamp_ns=started_ns,
    )
