"""RVC-specific local options and fixed worker launch; no Torch in the sidecar."""
import os
from pathlib import Path
import subprocess
from runtime_paths import resource_root, voice_worker_env
import sys
from threading import get_native_id

from models.owned_child import launch_owned
from .process import VCProcess
from .settings import start_options

ROOT = resource_root()
HELPER = ROOT / 'build/vrct-vc-worker'


def runtime_python(runtime):
    return runtime / ('venv/Scripts/python.exe' if sys.platform == 'win32' else 'venv/bin/python')


def worker_root():
    """Where -m finds the worker. A frozen _internal has Python 3.11 modules that would
    shadow the standard library of the runtime's own Python, so it stays off sys.path."""
    folder = ROOT / 'voice_worker'
    return folder if folder.is_dir() else ROOT


def _launch_owned(runtime, options, session):
    """The arguments the Linux helper builds, under a kill-on-close job."""
    return launch_owned([str(runtime_python(runtime)), '-u', '-m', 'integrations.rvc.live_worker',
        '--engine', str(runtime / 'engine'), '--assets', str(runtime / 'assets'),
        '--model', options['model'], '--session', session, '--index', options['index'],
        '--pitch', str(options['pitch']), '--index-rate', str(options['index_rate'])],
        env=voice_worker_env(), cwd=worker_root(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, realtime=True)


def _launch(runtime, options, session):
    if sys.platform == 'win32':
        return _launch_owned(runtime, options, session)
    owner = os.pidfd_open(get_native_id(), os.O_EXCL)
    try:
        return subprocess.Popen([str(HELPER), str(os.getpid()), str(owner),
            str(runtime_python(runtime)), str(runtime / 'engine'),
            str(runtime / 'assets'), options['model'], session, 'rvc', options['index'],
            str(options['pitch']), str(options['index_rate'])], env=voice_worker_env(), cwd=ROOT, pass_fds=(owner,),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    finally:
        os.close(owner)


class RVCProcess(VCProcess):
    def __init__(self, options, monitor=None, output=None):
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
        if (not runtime_python(self.runtime).is_file()
                or not (self.runtime / 'engine').is_dir()
                or not (self.runtime / 'assets').is_dir()):
            raise ValueError('vc_runtime_missing')
        super().__init__(engine='rvc', monitor=monitor, output=output)

    def _launch_worker(self):
        return _launch(self.runtime, self.options, self._session)
