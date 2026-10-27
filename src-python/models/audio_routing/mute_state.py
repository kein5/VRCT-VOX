"""Atomic durable mute intent, independent of debounced application preferences."""
import json
import os
from pathlib import Path
import tempfile


class MuteState:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return False
        if not isinstance(value, dict) or value.get('version') != 1 or type(value.get('muted')) is not bool:
            raise ValueError('invalid_mute_state')
        return value['muted']

    def write(self, muted):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.voice-mute-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'version': 1, 'muted': bool(muted)}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            if os.name == 'posix':
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
