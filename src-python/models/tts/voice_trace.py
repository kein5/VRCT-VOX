"""Opt-in, bounded diagnostic metadata. Never called from an audio callback."""
import json
import os
import stat
from uuid import UUID


def write_voice_trace(event_id, started_ns, first_write, outcome):
    """Best-effort JSONL after playback; no text, audio, URLs or exception data.

    Set VRCT_VOICE_TRACE to a local regular file only while measuring. Missing
    parents, full files and special files disable recording, not speech. The
    harness must require a complete trace; a missing row is not a fast trial.
    """
    path = os.environ.get("VRCT_VOICE_TRACE")
    if not path:
        return
    try:
        safe_id = str(UUID(event_id))
    except (ValueError, TypeError, AttributeError):
        safe_id = None
    row = {"schema": 1, "event_id": safe_id, "started_ns": started_ns,
           "first_write_ns": first_write[0] if first_write else None,
           "sample_rate": first_write[1] if first_write else None, "outcome": outcome}
    data = (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    for name in ("O_NONBLOCK", "O_NOFOLLOW", "O_BINARY"):
        flags |= getattr(os, name, 0)
    try:
        fd = os.open(path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if stat.S_ISREG(info.st_mode) and info.st_size + len(data) <= 8 * 1024 * 1024:
                os.write(fd, data)
        finally:
            os.close(fd)
    except OSError:
        pass
