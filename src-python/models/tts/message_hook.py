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


def microphone_event(update, translations, success, *, source_language, targets, selected_slot):
    """Only a successful selected translation of a trusted mic final can speak."""
    if update.source != "mic" or not update.is_final or update.state != "final":
        return None
    slots = [slot for slot, target in targets.items() if target.get("enable") is True]
    if selected_slot not in slots:
        return None
    index = slots.index(selected_slot)
    if index >= len(translations) or index >= len(success) or success[index] is not True:
        return None
    text = translations[index]
    if not isinstance(text, str) or not text.strip():
        return None
    identity = update.namespace + ":" + update.item_id
    return SpeechMessageEvent(
        event_id=identity, source="mic", original_text=update.text,
        translated_text=text, source_language=source_language,
        target_language=targets[selected_slot].get("language"), utterance_id=identity,
        revision=update.revision, timestamp_ns=update.received_ns,
    )
