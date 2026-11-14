"""How long each of the user's own inputs took to reach each output, in ms.

One trace per message: the user's speech (once recognized) or a typed chat.
Times count from a fixed origin per input, which the trace names:
- "send": the backend received the typed chat;
- "final": the realtime recognizer's final result arrived (the moment the
  user stopped speaking is not known to the app);
- "recognition": recognition of the cut-out speech began;
- "received": the recognized text reached the app, when neither is known.

The UI's flow panel and its overlays read the traces. Nothing is logged and
nothing leaves the PC; the text is the same the message log already shows.
"""
import time
from collections import OrderedDict
from threading import Lock

TEXT_LIMIT = 200
KEEP = 32


def _ms(ns):
    return max(0, round(ns / 1e6))


class IoTrace:
    def __init__(self, trace_id, source, text, origin, origin_ns):
        self.id = str(trace_id)
        self.source = source
        self.text = text[:TEXT_LIMIT]
        self.translation = ""
        self.origin = origin
        self.origin_ns = origin_ns
        self.stages = {}
        self.outputs = {}
        self.published = False
        # The message thread and the TTS thread both write; speech may start first.
        self._lock = Lock()

    def stage(self, name, ms):
        if ms is not None:
            with self._lock:
                self.stages[name] = max(0, round(ms))

    def output(self, name, state, at_ns=None, **detail):
        at = None if at_ns is None else _ms(at_ns - self.origin_ns)
        with self._lock:
            self.outputs[name] = {"state": state, "at_ms": at, **detail}

    def speech_queued(self, accepted):
        with self._lock:
            if self.outputs.get("speech", {}).get("state") != "playing":
                self.outputs["speech"] = {"state": "queued" if accepted else "not_spoken", "at_ms": None}

    def to_dict(self):
        with self._lock:
            return {"id": self.id, "input": self.source, "text": self.text,
                    "translation": self.translation[:TEXT_LIMIT], "origin": self.origin, "stages": dict(self.stages),
                    "outputs": {name: dict(value) for name, value in self.outputs.items()}}


class IoTraces:
    """The recent traces, so speech that starts later can add its time to its message."""

    def __init__(self, emit):
        self._emit = emit
        self._lock = Lock()
        self._traces = OrderedDict()

    def begin(self, trace_id, source, text, origin, origin_ns=None):
        # Kept from the start: speech of the original chat can begin before translation ends.
        trace = IoTrace(trace_id, source, text, origin, time.monotonic_ns() if origin_ns is None else origin_ns)
        with self._lock:
            self._traces[trace.id] = trace
            self._traces.move_to_end(trace.id)
            while len(self._traces) > KEEP:
                self._traces.popitem(last=False)
        return trace

    def publish(self, trace):
        with self._lock:
            trace.published = True
        self._emit(trace.to_dict())

    def speech_started(self, trace_id, timestamp_ns, *, converted, conversion_ms=None):
        """The first audio of a message's speech was written (or sent to the conversion)."""
        detail = {"converted": bool(converted)}
        if converted and conversion_ms is not None:
            detail["conversion_ms"] = conversion_ms
        with self._lock:
            trace = self._traces.get(str(trace_id))
            if trace is None:
                return False
            # Under the same lock as publish(): either it emits this time, or this call does.
            trace.output("speech", "playing", timestamp_ns, **detail)
            published = trace.published
        if published:
            self._emit(trace.to_dict())
        return True
