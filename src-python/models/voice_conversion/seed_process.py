"""Seed-specific validation and fixed worker launch; shared lifetime in process.py."""
import os
from pathlib import Path
import subprocess
from runtime_paths import resource_root, external_process_env
from threading import get_native_id

from .process import VCProcess

ROOT = resource_root()
HELPER = ROOT / 'build/vrct-vc-worker'


def _launch(runtime, reference, session):
    owner = os.pidfd_open(get_native_id(), os.O_EXCL)
    try:
        return subprocess.Popen([str(HELPER), str(os.getpid()), str(owner),
            str(runtime / 'venv/bin/python'), str(runtime / 'engine'),
            str(runtime / 'assets'), str(reference), session], env=external_process_env(), cwd=ROOT, pass_fds=(owner,),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    finally:
        os.close(owner)


class SeedProcess(VCProcess):
    def __init__(self, options, monitor=None):
        if (not isinstance(options, dict) or set(options) != {'runtime', 'reference'}
                or any(not isinstance(v, str) or not v or '\0' in v for v in options.values())):
            raise ValueError('vc_options_invalid')
        self.runtime = Path(options['runtime']).expanduser().resolve()
        self.reference = Path(options['reference']).expanduser().resolve()
        if (not (self.runtime / 'venv/bin/python').is_file()
                or not (self.runtime / 'engine').is_dir()
                or not (self.runtime / 'assets').is_dir() or not self.reference.is_file()):
            raise ValueError('vc_runtime_missing')
        super().__init__(engine='seed-vc', monitor=monitor)

    def _launch_worker(self):
        return _launch(self.runtime, self.reference, self._session)
