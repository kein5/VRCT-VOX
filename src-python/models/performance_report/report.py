"""Puts a session's numbers and the PC's parts into one report, or refuses to."""
import re

from .schema import SCHEMA, ascii_text, fault_of

_DEVICE = re.compile(r"[0-9A-Za-z]{1,20}")
_MODEL = re.compile(r"[0-9a-z][0-9a-z._-]{0,59}")


def _gigabytes(value):
    return round(float(value), 1) if type(value) in (int, float) and 0 <= value <= 1024 * 8 else 0.0


def _parts(cpu, gpus):
    """CPU and GPUs as the report carries them: names in printable ASCII, sizes rounded."""
    model = ascii_text((cpu or {}).get("model"), 100) or "unknown"
    logical = (cpu or {}).get("logical")
    processor = {"model": model, "logical": logical if type(logical) is int and 1 <= logical <= 1024 else 1,
                 "memory_gb": _gigabytes((cpu or {}).get("memory_gb"))}
    cards = []
    for row in (gpus or [])[:8]:
        name = ascii_text(row.get("name"), 100)
        if name:
            kind = row.get("kind")
            cards.append({"name": name, "kind": kind if kind in ("gpu", "igpu") else "other",
                          "memory_gb": min(1024.0, _gigabytes(row.get("memory_gb")))})
    return processor, cards


def build(*, app_version, os_name, os_version, session_id, sequence, uptime_s, vrchat, cpu, gpus, snapshot):
    """A report that may be sent, from Collector.snapshot() and what the PC is made of.

    A device or model that is not a plain identifier is left out rather than sent, and a
    report that still holds anything outside the list raises: nothing questionable leaves.
    """
    processor, cards = _parts(cpu, gpus)
    features = {}
    for name, row in snapshot["features"].items():
        entry = {"used_s": row["used_s"]}
        if isinstance(row.get("device"), str) and _DEVICE.fullmatch(row["device"]):
            entry["device"] = row["device"]
        if isinstance(row.get("model"), str) and _MODEL.fullmatch(row["model"]):
            entry["model"] = row["model"]
        features[name] = entry
    report = {
        "schema": SCHEMA, "app_version": app_version, "os": os_name,
        "os_version": ascii_text(os_version, 60) or "unknown",
        "session_id": session_id, "sequence": sequence, "uptime_s": int(uptime_s), "vrchat": bool(vrchat),
        "cpu": processor, "gpus": cards, "features": features,
        "timings": snapshot["timings"], "counters": snapshot["counters"], "errors": snapshot["errors"],
    }
    fault = fault_of(report)
    if fault:
        raise ValueError("performance_report_invalid:" + fault)
    return report
