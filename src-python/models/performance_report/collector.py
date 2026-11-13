"""Adds up what a session measured: how long each feature ran, how late things were, how often they failed.

Thread-safe and cheap: callers on audio or caption paths only add a number under a lock.
Nothing here knows about text, audio or names; a caller can only give a listed name and a number.
"""
import random
import re
from threading import Lock
from time import monotonic

from .schema import COUNTERS, FEATURES, TIMINGS

# Percentiles come from this many samples at most; with more, each sample is kept with
# equal chance (reservoir sampling), so a long session costs no more than a short one.
RESERVOIR = 512
MAX_ERROR_CODES = 50


class _Timing:
    def __init__(self, rng):
        self.count, self.largest, self.samples, self._rng = 0, 0.0, [], rng

    def add(self, value):
        self.count += 1
        self.largest = max(self.largest, value)
        if len(self.samples) < RESERVOIR:
            self.samples.append(value)
        else:
            slot = self._rng.randrange(self.count)
            if slot < RESERVOIR:
                self.samples[slot] = value

    def summary(self):
        ordered = sorted(self.samples)

        def at(share):
            # Nearest rank: the smallest value with at least that share of the samples at or below it.
            return ordered[max(0, min(len(ordered) - 1, -(-len(ordered) * share // 100) - 1))]
        return {"n": self.count, "p50": round(at(50), 1), "p95": round(at(95), 1), "max": round(self.largest, 1)}


class Collector:
    def __init__(self, clock=monotonic, seed=None):
        self._clock, self._lock, self._rng = clock, Lock(), random.Random(seed)
        self._features, self._timings, self._counters, self._errors = {}, {}, {}, {}

    def feature(self, name, active, device=None, model=None):
        """Says a feature is on or off now, and on which device and model it runs."""
        if name not in FEATURES:
            raise ValueError("performance_report_feature_unknown")
        now = self._clock()
        with self._lock:
            row = self._features.setdefault(name, {"used": 0.0, "since": None, "device": None, "model": None})
            if row["since"] is not None:
                row["used"] += max(0.0, now - row["since"])
            row["since"] = now if active else None
            if active:
                row["device"], row["model"] = device, model

    def timing(self, name, milliseconds):
        if name not in TIMINGS:
            raise ValueError("performance_report_timing_unknown")
        if type(milliseconds) not in (int, float) or not 0 <= milliseconds <= 3_600_000:
            return  # Not a delay: a clock that stepped, or a value out of any use.
        with self._lock:
            if name not in self._timings:
                self._timings[name] = _Timing(self._rng)
            self._timings[name].add(float(milliseconds))

    def count(self, name, amount=1):
        if name not in COUNTERS:
            raise ValueError("performance_report_counter_unknown")
        if type(amount) is not int or amount < 0:
            return
        with self._lock:
            self._counters[name] = min(1_000_000_000, self._counters.get(name, 0) + amount)

    def error(self, code):
        """Counts a failure by its fixed code. Anything that is not such a code is not counted."""
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", code):
            return
        with self._lock:
            if code in self._errors or len(self._errors) < MAX_ERROR_CODES:
                self._errors[code] = min(1_000_000, self._errors.get(code, 0) + 1)

    def snapshot(self):
        """The session so far, in the report's own form. Features still on count up to now."""
        now = self._clock()
        with self._lock:
            features = {}
            for name, row in self._features.items():
                used = row["used"] + (max(0.0, now - row["since"]) if row["since"] is not None else 0.0)
                if used <= 0 and row["since"] is None:
                    continue
                entry = {"used_s": int(used)}
                entry.update({key: row[key] for key in ("device", "model") if row[key]})
                features[name] = entry
            return {
                "features": features,
                "timings": {name: timing.summary() for name, timing in self._timings.items() if timing.count},
                "counters": dict(self._counters),
                "errors": dict(self._errors),
            }
