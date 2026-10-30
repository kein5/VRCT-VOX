"""Defer automatic cyclic collection until PCM writing AND drain have ended.

CPython's ordinary reference counting continues. The speech scheduler requests
cancellation after 30 s; output/HTTP waits also have their own timeouts.
This is not a permanent GC disable, nor a change to thresholds.
Explicit gc.collect() by another component is not intercepted.
"""
from contextlib import contextmanager
import gc
from threading import Lock

_lock = Lock()
_users = 0
_restore_enabled = False


@contextmanager
def defer_cyclic_gc():
    global _users, _restore_enabled
    with _lock:
        if _users == 0:
            _restore_enabled = gc.isenabled()
            if _restore_enabled:
                gc.disable()
        _users += 1
    try:
        yield
    finally:
        with _lock:
            _users -= 1
            if _users == 0 and _restore_enabled:
                gc.enable()
