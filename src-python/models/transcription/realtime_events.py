"""Single-loop, bounded subtitle state; no audio, translation, OSC or TTS."""
from collections import OrderedDict
import re
from dataclasses import dataclass, field

PREFIX = 'conversation.item.input_audio_transcription.'


@dataclass(frozen=True)
class TranscriptUpdate:
    source: str
    namespace: str
    item_id: str
    revision: int
    text: str
    is_final: bool
    state: str
    # Transport receipt, not acoustic capture or utterance-end time. The pure
    # reducer leaves this unset; the transport stamps it before queueing.
    received_ns: int = field(default=0, compare=False)
    # The code a final reports in "languages" (speech.cpp 0.10.0), else ''.
    # Detected by the model, not a confidence: only a translation source hint.
    language: str = field(default='', compare=False)


@dataclass
class _Pending:
    text: str = ''
    revision: int = 0


class TranscriptEvents:
    """Only known live items can produce a final, at most once while tracked.

    A new connection must have a new namespace. Terminal IDs and event IDs are
    bounded replay protection, not an unlimited history of a malicious peer.
    """
    def __init__(self, source, namespace):
        if source not in ('mic', 'speaker') or not isinstance(namespace, str) or not 0 < len(namespace) <= 128:
            raise ValueError('invalid_session_identity')
        self.source, self.namespace = source, namespace
        self.closed = False
        self.clearing = False
        self._pending = {}
        self._terminal, self._events = OrderedDict(), OrderedDict()

    @staticmethod
    def _remember(history, key, limit):
        history[key] = None
        while len(history) > limit:
            history.popitem(last=False)

    def _emit(self, item_id, text, state, language=''):
        pending = self._pending[item_id]
        pending.text = text
        pending.revision += 1
        return TranscriptUpdate(self.source, self.namespace, item_id,
            pending.revision, text, state == 'final', state, language=language)

    @staticmethod
    def _detected(event):
        rows = event.get('languages')
        code = rows[0].get('code') if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
        return code if isinstance(code, str) and re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?', code) else ''

    def _retire(self, item_id):
        self._pending.pop(item_id, None)
        self._remember(self._terminal, item_id, 256)

    def _discard(self):
        updates = tuple(self._emit(item, '', 'discarded') for item in self._pending)
        for item in tuple(self._pending):
            self._retire(item)
        return updates

    def begin_clear(self):
        if self.closed:
            return ()
        self.clearing = True
        return self._discard()

    @property
    def pending_ids(self):
        """Snapshot for the transport's bounded utterance deadlines."""
        return tuple(self._pending)

    def close(self):
        self.closed = True
        return self._discard()

    def _fail(self, reason):
        self.close()
        raise ValueError(reason)

    def accept(self, event):
        if self.closed:
            return ()
        if not isinstance(event, dict):
            self._fail('invalid_event')
        event_id, kind = event.get('event_id'), event.get('type')
        if not isinstance(event_id, str) or not 0 < len(event_id) <= 256 or not isinstance(kind, str):
            self._fail('invalid_event')
        if event_id in self._events:
            return ()
        self._remember(self._events, event_id, 512)
        if kind == 'input_audio_buffer.cleared':
            updates = self._discard()
            self.clearing = False
            return updates
        names = ('input_audio_buffer.speech_started', 'input_audio_buffer.committed',
                 PREFIX + 'delta', PREFIX + 'completed', PREFIX + 'failed')
        if kind not in names:
            return ()
        item_id = event.get('item_id')
        if not isinstance(item_id, str) or not 0 < len(item_id) <= 256:
            self._fail('invalid_item')
        if self.clearing:
            self._retire(item_id)
            return ()
        if item_id in self._terminal:
            return ()
        if kind in names[:2]:
            if item_id not in self._pending:
                if len(self._pending) >= 8:
                    self._fail('pending_limit')
                self._pending[item_id] = _Pending()
            return ()
        if item_id not in self._pending:
            return ()
        if kind == PREFIX + 'failed' or (kind == PREFIX + 'completed' and event.get('stop') != 'complete'):
            update = self._emit(item_id, '', 'discarded')
            self._retire(item_id)
            return (update,)
        text = event.get('delta' if kind == PREFIX + 'delta' else 'transcript')
        if not isinstance(text, str):
            self._fail('invalid_text')
        if kind == PREFIX + 'delta':
            text = self._pending[item_id].text + text
        if len(text) > 4000:
            self._fail('text_limit')
        state = 'partial' if kind == PREFIX + 'delta' else 'final'
        update = self._emit(item_id, text, state, self._detected(event) if state == 'final' else '')
        if state == 'final':
            self._retire(item_id)
        return (update,)
