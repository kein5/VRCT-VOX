# SPDX-License-Identifier: GPL-3.0-only
"""One external VC session; failed and stopped sessions never resume."""
from threading import Lock

import numpy as np


def require_fresh_block(due_ns, now_ns, block_ms):
    if (now_ns - due_ns) / 1e6 > 2 * block_ms:
        raise TimeoutError('vc_overload')


class BlockSession:
    def __init__(self, engine):
        self.engine = engine
        self.status = 'ready'
        self.error = None
        self._lock = Lock()

    def stop(self):
        with self._lock:
            self.status = 'stopped'

    def convert(self, data):
        with self._lock:
            if self.status in ('failed', 'stopped'):
                return None
            self.status = 'converting'
        try:
            if self.engine.config.function != 'vc':
                raise ValueError('bypass_forbidden')
            if data.shape != (self.engine.block_frame,) or not np.isfinite(data).all():
                raise ValueError('invalid_input_block')
            output = self.engine._process_block(data)
            if self.engine.config.function != 'vc':
                raise ValueError('bypass_forbidden')
            status = self.engine.last_block_status
            if status not in ('converted', 'vad_silence'):
                raise ValueError('conversion_not_confirmed')
            if output.shape != data.shape or not np.isfinite(output).all():
                raise ValueError('invalid_output_block')
            if np.any(data) and np.array_equal(output, data):
                raise ValueError('passthrough_forbidden')
        except Exception as exc:
            with self._lock:
                if self.status != 'stopped':
                    self.status = 'failed'
                    self.error = str(exc)
            return None
        with self._lock:
            if self.status == 'stopped':
                return None
            self.status = status
            return output
