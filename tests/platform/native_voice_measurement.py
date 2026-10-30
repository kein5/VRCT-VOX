"""Conservative clock bounds for an awake, local native UI measurement.

Browser performance.now() and Python monotonic_ns() have different origins.
Bracket each browser read with OS-clock reads; never assume symmetric IPC.
Use samples before AND after the event. Raw samples must accompany a result.
"""
import math
import time


def clock_offset(samples, *, padding_ns=1_000_000):
    lower, upper = -math.inf, math.inf
    previous_end, previous_browser = -1, -1
    if not samples or padding_ns < 0:
        raise ValueError("missing clock samples or negative timer padding")
    for sample in samples:
        before, after = sample["before_ns"], sample["after_ns"]
        browser = sample["browser_ms"] * 1e6
        if (not all(math.isfinite(v) for v in (before, after, browser))
                or before < previous_end or after < before or browser < previous_browser):
            raise ValueError("unordered or invalid clock sample")
        lower = max(lower, before - browser - padding_ns)
        upper = min(upper, after - browser + padding_ns)
        previous_end, previous_browser = after, browser
    if lower > upper:
        raise ValueError("clock offset changed outside observed bounds")
    return lower, upper


def elapsed_bounds(first_write_ns, ui_ms, samples, *, padding_ns=1_000_000):
    lower_offset, upper_offset = clock_offset(samples, padding_ns=padding_ns)
    if (not math.isfinite(ui_ms) or not math.isfinite(first_write_ns)
            or not samples[0]["browser_ms"] <= ui_ms <= samples[-1]["browser_ms"]):
        raise ValueError("UI event was not bracketed by calibration")
    # The event read itself has the same declared timer quantization allowance.
    start_lower = ui_ms * 1e6 + lower_offset - padding_ns
    start_upper = ui_ms * 1e6 + upper_offset + padding_ns
    if first_write_ns < start_upper:
        raise ValueError("negative or unresolved elapsed time")
    return {"lower_ms": (first_write_ns - start_upper) / 1e6,
            "upper_ms": (first_write_ns - start_lower) / 1e6,
            "calibration_width_ms": (start_upper - start_lower) / 1e6}


def calibrate(ui, count=25):
    samples = []
    for _ in range(count):
        before = time.monotonic_ns()
        browser = ui.evaluate("return performance.now()")
        after = time.monotonic_ns()
        samples.append({"before_ns": before, "browser_ms": browser, "after_ns": after})
    return samples


def exact_pcm(reference, observed):
    """Reject inserted silence, lost samples or extra speech in seeded tests."""
    offset = observed.find(reference) if reference and any(reference) and not (len(reference) % 2 or len(observed) % 2) else -1
    return {'valid': offset >= 0 and offset % 2 == 0 and not any(observed[:offset]) and not any(observed[offset + len(reference):]),
            'offset_bytes': offset, 'reference_bytes': len(reference), 'observed_bytes': len(observed)}


def summarize_trials(rows, *, real_inference, target_p95_ms=800):
    if not math.isfinite(target_p95_ms) or target_p95_ms <= 0:
        raise ValueError('invalid latency budget')
    result = {"count": len(rows), "minimum_count": 30, "method": "nearest_rank",
              "boundary": "trusted UI click capture to first nonzero output write completion",
              "target_p50_ms": 350, "target_p95_ms": target_p95_ms,
              "max_clock_interval_ms": 5, "p50_upper_ms": None, "p95_upper_ms": None}
    for row in rows:
        bounds = [row.get(key, math.nan) for key in ("lower_ms", "upper_ms", "calibration_width_ms")]
        if (not row.get("valid") or row.get("outcome") != "completed" or not row.get("warm")
                or not all(math.isfinite(value) for value in bounds)
                or not 0 <= bounds[0] <= bounds[1] or not 0 <= bounds[2] <= 5):
            return {**result, "verdict": "invalid_measurement"}
    if rows:
        for suffix in ("lower", "upper"):
            ordered = sorted(row[f"{suffix}_ms"] for row in rows)
            for label, rank in (("p50", .5), ("p95", .95)):
                result[f"{label}_{suffix}_ms"] = ordered[math.ceil(len(rows) * rank) - 1]
    verdict = ("fixture_only" if not real_inference else "insufficient_samples" if len(rows) < 30
               else "pass" if result["p50_upper_ms"] < 350 and result["p95_upper_ms"] < target_p95_ms
               else "target_not_met")
    return {**result, "verdict": verdict}
