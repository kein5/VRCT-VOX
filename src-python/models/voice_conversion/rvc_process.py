"""RVC-specific local options and fixed worker launch; no Torch in the sidecar."""
import os
from pathlib import Path
import subprocess
from runtime_paths import resource_root, external_process_env
from threading import get_native_id

from .process import VCProcess
from .settings import start_options

ROOT = resource_root()
HELPER = ROOT / 'build/vrct-vc-worker'


def _launch(runtime, options, session):
    owner = os.pidfd_open(get_native_id(), os.O_EXCL)
    try:
        return subprocess.Popen([str(HELPER), str(os.getpid()), str(owner),
            str(runtime / 'venv/bin/python'), str(runtime / 'engine'),
            str(runtime / 'assets'), options['model'], session, 'rvc', options['index'],
            str(options['pitch']), str(options['index_rate'])], env=external_process_env(), cwd=ROOT, pass_fds=(owner,),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    finally:
        os.close(owner)


class RVCProcess(VCProcess):
    def __init__(self, options):
        self.options = start_options('converted', options)
        if self.options.get('engine') != 'rvc':
            raise ValueError('vc_options_invalid')
        self.runtime = Path(options['runtime']).expanduser().resolve()
        for key in ('model', 'index'):
            if self.options[key]:
                path = Path(self.options[key]).expanduser().resolve()
                if not path.is_file():
                    raise ValueError('vc_runtime_missing')
                self.options[key] = str(path)
        if (not (self.runtime / 'venv/bin/python').is_file()
                or not (self.runtime / 'engine').is_dir()
                or not (self.runtime / 'assets').is_dir()):
            raise ValueError('vc_runtime_missing')
        super().__init__(engine='rvc')

    def _launch_worker(self):
        return _launch(self.runtime, self.options, self._session)
