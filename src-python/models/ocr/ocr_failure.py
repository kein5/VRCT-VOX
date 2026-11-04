"""Bound repeated OCR diagnostics without retaining exceptions or frames."""

from __future__ import annotations

import time
from typing import Callable, Optional


FAILURE_SUMMARY_INTERVAL_SEC = 60.0


class OcrFailureLog:
    """One operation's failure streak; call failure() inside the except block.

    The owner serializes access and calls report() even while work is skipped.
    Only the exception type and message are retained, never its traceback.
    """

    def __init__(self, origin: str, traceback_log: Callable[[], None], log: Callable[[str], None]) -> None:
        self._origin = origin
        self._traceback_log = traceback_log
        self._log = log
        self.reset()

    def reset(self) -> None:
        self._kind = None
        self._count = 0
        self._suppressed = 0
        self._last_report = 0.0

    @property
    def active(self) -> bool:
        """A failure remains unresolved until the owner observes success."""
        return self._kind is not None

    def failure(self, exc: Exception) -> None:
        now = time.monotonic()
        kind = (type(exc), str(exc))
        if kind != self._kind:
            self._kind = kind
            self._count = 1
            self._suppressed = 0
            self._last_report = now
            self._traceback_log()
            return
        self._count += 1
        self._suppressed += 1
        self.report(now)

    def report(self, now: float) -> None:
        if self._suppressed and now - self._last_report >= FAILURE_SUMMARY_INTERVAL_SEC:
            self._log(f"{self._origin}: suppressed {self._suppressed} repeated failures "
                      f"in {now - self._last_report:.0f}s "
                      f"({self._kind[0].__name__}, total={self._count})")
            self._suppressed = 0
            self._last_report = now

    def success(self) -> None:
        if self._kind is not None:
            self._log(f"{self._origin}: recovered after {self._count} failures "
                      f"({self._suppressed} repeats since last summary)")
            self.reset()


class OcrRetry:
    """One stage's retry schedule, independent of recognition's three-strike policy."""

    def __init__(self, log: OcrFailureLog) -> None:
        self.log = log
        self.reset()

    def reset(self) -> None:
        self.delay = 0.0
        self.retry_at = 0.0
        self.log.reset()

    def failure(self, exc: Optional[Exception] = None) -> None:
        # A native capture wrapper may have already logged and suppressed it.
        if exc is not None:
            self.log.failure(exc)
        self.delay = min(30.0, max(1.0, self.delay * 2.0))
        self.retry_at = time.monotonic() + self.delay

    def success(self) -> None:
        self.log.success()
        self.delay = 0.0
        self.retry_at = 0.0
