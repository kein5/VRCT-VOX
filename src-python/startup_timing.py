"""How long each startup stage took, kept across starts.

process.log is emptied at every start, so a slow start is gone by the time
anyone looks for it. finish() appends one JSON line to startup_timing.log. It
holds stage names, endpoint names and numbers: no paths, devices or settings.

Each stage has its wall-clock and CPU seconds. Far more wall than CPU means the
stage was waiting: on the disk, an audio driver, a virus scanner or a busy PC.
Close numbers mean real work, such as compiling modules after an update.
"""
import json
import time

_LOG_FILE = "startup_timing.log"
_LOG_LIMIT = 256 * 1024
_LOG_KEEP = 64 * 1024
_SLOW_GETTER_SECONDS = 0.1
_SLOW_GETTERS_KEPT = 5

# The log lines of Controller.init(), and the stage each one ends.
_STAGE_ENDED_BY = {
    "Start Initialization": "construct_controller",
    "Init Translation Engine Status": "check_model_weights",
    "Init Transcription Engine Status": "check_translation_engines",
    "Set Translation Engine": "check_transcription_engines",
    "Init Device Manager": "apply_engines",
    "Init Overlay": "select_audio_devices",
    "Update settings": "start_services",
}

_started_at = time.time()
_started = _last = (time.perf_counter(), time.process_time())
_stages = []
_slow_getters = []
_system_before = None
_finished = False


def _systemTimes():
    try:
        import psutil
        return psutil.cpu_times()
    except Exception:
        return None


def mark(stage):
    """End a stage: the time since the previous mark belongs to it."""
    global _last, _system_before
    if _finished:
        return
    now = (time.perf_counter(), time.process_time())
    _stages.append([stage, round(now[0] - _last[0], 3), round(now[1] - _last[1], 3)])
    _last = now
    if _system_before is None:
        _system_before = _systemTimes()


def note(log):
    """Called with every printLog message; startup stages end on known lines."""
    stage = _STAGE_ENDED_BY.get(log) if isinstance(log, str) else None
    if stage is not None:
        mark(stage)


def timed(endpoint, getter):
    """Remember a slow startup getter: one of them can hold the loading screen."""
    def run(*args, **kwargs):
        if _finished:
            return getter(*args, **kwargs)
        began = time.perf_counter()
        try:
            return getter(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - began
            if elapsed >= _SLOW_GETTER_SECONDS:
                _slow_getters.append([endpoint, round(elapsed, 3)])
    return run


def _systemBusyPercent():
    """All CPUs over the startup, this process included. None if unknown."""
    after = _systemTimes()
    if _system_before is None or after is None:
        return None
    total = sum(after) - sum(_system_before)
    if total <= 0:
        return None
    return round(100 * (1 - (after.idle - _system_before.idle) / total), 1)


def _beforePython():
    """Seconds from process creation to the first line of Python code."""
    try:
        import psutil
        return round(_started_at - psutil.Process().create_time(), 3)
    except Exception:
        return None


def summary():
    now = (time.perf_counter(), time.process_time())
    return {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(_started_at)),
        "total": round(now[0] - _started[0], 3),
        "cpu": round(now[1] - _started[1], 3),
        "before_python": _beforePython(),
        "system_busy_percent": _systemBusyPercent(),
        "stages": list(_stages),
        "slow_getters": sorted(_slow_getters, key=lambda row: -row[1])[:_SLOW_GETTERS_KEPT],
    }


def finish():
    """Write this start's line. A failure here must not fail the start."""
    global _finished
    if _finished:
        return
    from utils import errorLogging, openTraceLog, printLog
    try:
        mark("collect_settings")
        result = summary()
        _finished = True
        printLog("Startup timing", result)
        _path, stream = openTraceLog(_LOG_FILE, limit=_LOG_LIMIT, keep=_LOG_KEEP)
        with stream:
            stream.write(json.dumps(result) + "\n")
    except Exception:
        errorLogging()
