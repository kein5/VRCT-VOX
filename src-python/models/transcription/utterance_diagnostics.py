"""Lazy, bounded speech diagnostics. No audio, text, timers or worker threads."""

from collections import Counter, deque
from math import ceil
from threading import Lock
from time import monotonic


SUMMARY_INTERVAL_SECONDS = 60.0
SAMPLE_LIMIT = 256
# Diagnostic thresholds only; none of these change a pipeline deadline.
# VAD: twice the default 24 * 32 ms hangover; buffer: the 15 s safety net.
# ASR/translation: half their 10 s Google/web timeout; total: both budgets.
# Realtime: half the 15 s pending limit and half the 2 s delivery lifetime.
SLOW_MS = {
    "vad_wait_ms": 1536,
    "vad_buffer_ms": 15000,
    "queue_ms": 1000,
    "asr_ms": 5000,
    "translate_ms": 5000,
    "output_ms": 1000,
    "total_ms": 10000,
    "realtime_pending_ms": 7500,
    "realtime_queue_ms": 1000,
    "realtime_translate_ms": 1000,
    "realtime_total_ms": 2000,
}
STAGES = frozenset(SLOW_MS) | {"segment_ms"}
EVENTS = frozenset((
    "speech_start", "speech_end", "vad_finalize", "vad_safety_finalize",
    "vad_interim", "vad_accumulate", "audio_chunk", "audio_drop",
    "asr_success", "asr_failure", "asr_error", "message", "message_aborted",
    "realtime_final", "realtime_empty_final", "realtime_delivery", "realtime_processed",
))


def _print_log(message):
    # Importing this module (also used by model-free realtime tests) has no
    # logger, stdout writer or application initialization side effects.
    from utils import printLog
    printLog(message)


class _Samples:
    def __init__(self):
        self.values = deque(maxlen=SAMPLE_LIMIT)
        self.count = 0
        self.maximum = 0.0

    def add(self, value):
        self.values.append(value)
        self.count += 1
        self.maximum = max(self.maximum, value)

    def summary(self):
        values = sorted(self.values)
        return (
            f"n={self.count},samples={len(values)},"
            f"p50={values[ceil(len(values) * .50) - 1]:.1f},"
            f"p95={values[ceil(len(values) * .95) - 1]:.1f},max={self.maximum:.1f}"
        )


class _Source:
    def __init__(self):
        self.lock = Lock()
        self.started = None
        self.counts = Counter()
        self.stages = {}
        self.drops = 0


class UtteranceDiagnostics:
    """Counts/max cover the window; nearest-rank quantiles use its last 256 values.

    Keys are fixed so malformed callers cannot grow the collector. A source's
    first event opens a window. The first event >=60 s later flushes the previous
    window and opens the next; there are no catch-up reports or idle wakeups.
    Formatting and printLog happen outside the statistics locks.
    """

    def __init__(self, *, clock=monotonic, log=_print_log):
        self._clock, self._log = clock, log
        self._sources = {source: _Source() for source in ("mic", "speaker")}

    @staticmethod
    def _snapshot(source, state, now, reason):
        if not state.counts:
            return None
        result = (source, now - state.started, reason, state.counts, state.stages, state.drops)
        state.started = None
        state.counts, state.stages = Counter(), {}
        return result

    def _emit(self, snapshot):
        if snapshot is None:
            return
        source, elapsed, reason, counts, stages, drops = snapshot
        counters = " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        timings = " ".join(f"{key}({value.summary()})" for key, value in sorted(stages.items()))
        self._log(
            f"[utterance-summary][{source}] reason={reason} window={elapsed:.1f}s "
            f"{counters} drop_run={drops}" + (f" {timings}" if timings else "")
        )

    def _window(self, source, state, now):
        snapshot = None
        if state.started is not None and now - state.started >= SUMMARY_INTERVAL_SECONDS:
            snapshot = self._snapshot(source, state, now, "interval")
        if not state.counts:
            state.started = now
        return snapshot

    def record(self, source, event, stages=None, detail=None, *, immediate=False):
        if source not in self._sources or event not in EVENTS:
            return
        stages = {key: max(0.0, float(value)) for key, value in (stages or {}).items() if key in STAGES}
        state = self._sources[source]
        with state.lock:
            snapshot = self._window(source, state, self._clock())
            state.counts[event] += 1
            for key, value in stages.items():
                if key not in state.stages:
                    state.stages[key] = _Samples()
                state.stages[key].add(value)
        # Never retain the diagnostic string: only numeric, fixed-key metadata
        # belongs in a summary, even if a caller later gains more detail.
        if detail is not None and (immediate or any(
            value >= SLOW_MS.get(key, float("inf")) for key, value in stages.items()
        )):
            self._log(detail)
        self._emit(snapshot)

    def queue_result(self, source, dropped):
        if source not in self._sources:
            return
        state = self._sources[source]
        onset = recovered = 0
        with state.lock:
            if not dropped and not state.drops:
                return  # Successful enqueue alone is not diagnostic activity.
            snapshot = self._window(source, state, self._clock())
            if dropped:
                onset = not state.drops
                state.drops += 1
                state.counts["audio_drop"] += 1
            else:
                recovered, state.drops = state.drops, 0
        if onset:
            self._log(f"audio_queue is full; dropped the oldest queued chunk to keep up [source={source}]")
        self._emit(snapshot)
        if recovered:
            self._log(f"[ASR-queue][{source}] recovered dropped={recovered} repeated={recovered - 1}")

    def flush(self, source=None, *, reason="stop"):
        for name in ((source,) if source is not None else ("mic", "speaker")):
            if name not in self._sources:
                continue
            state = self._sources[name]
            with state.lock:
                snapshot = self._snapshot(name, state, self._clock(), reason)
                drops, state.drops = state.drops, 0
            self._emit(snapshot)
            if drops:
                # Stopping without another enqueue is not evidence of recovery.
                self._log(f"[ASR-queue][{name}] {reason} dropped={drops} repeated={drops - 1} recovery=unconfirmed")


utterance_diagnostics = UtteranceDiagnostics()
