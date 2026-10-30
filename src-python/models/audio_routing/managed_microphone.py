"""Create OS-owned endpoints without restarting audio or depending on an AppImage mount."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from runtime_paths import external_process_env
from .pipewire_gate import parse_graph

OWNER = 'vrct-tts-service-v1'
SERVICE_NAMES = tuple(f'vrct-managed-{part}.service' for part in ('source', 'tts', 'vc'))


def loopback_commands(binary):
    """Fixed route equivalent to 90-vrct-managed.conf, with a distinct ownership marker."""
    common = {'node.virtual': True, 'vrct.managed.route': 'v1',
              'vrct.managed.owner': OWNER, 'priority.session': -100, 'state.restore-props': False}
    commands = {}
    for part, service in zip(('source', 'tts', 'vc'), SERVICE_NAMES):
        capture = dict(common, **{'media.class': 'Audio/Sink',
            'node.name': 'vrct.managed.mix' if part == 'source' else f'vrct.managed.{part}',
            'node.description': {'source': 'VRCT Managed Virtual Microphone Input',
                                 'tts': 'VRCT Managed TTS Input', 'vc': 'VRCT Managed VC Input'}[part]})
        if part == 'source':
            playback = dict(common, **{'media.class': 'Audio/Source', 'node.name': 'vrct.managed.source',
                'node.description': 'VRCT Managed Virtual Microphone', 'node.passive': True,
                'node.param.Props': {'mute': True}})
        else:
            playback = dict(common, **{'node.name': f'vrct.managed.{part}.output',
                'target.object': 'vrct.managed.mix', 'node.dont-fallback': True,
                'node.dont-reconnect': True})
        commands[service] = [binary, '--name', f'vrct-managed-{part}', '--channels', '1',
            '--channel-map', 'MONO', '--capture-props', json.dumps(capture),
            '--playback-props', json.dumps(playback)]
    return commands


def service_units(binary):
    if not re.fullmatch(r'/[A-Za-z0-9_./+\-]+', binary):
        raise RuntimeError('managed_setup_tools_missing')
    units = {}
    for name, args in loopback_commands(binary).items():
        # JSON's ASCII string quoting also quotes systemd's argv grammar. Fixed
        # arguments contain no dollar/percent expansions or shell commands.
        command = ' '.join(json.dumps(arg) for arg in args)
        units[name] = (
            '# VRCT managed microphone v1; created by VRCT-VOX\n'
            '[Unit]\nDescription=VRCT managed audio endpoint\n'
            'After=pipewire.service wireplumber.service\n'
            '[Service]\nType=exec\nExecStart='+command+'\n'
            'Restart=always\nRestartSec=2\nTimeoutStopSec=5\n'
            '[Install]\nWantedBy=default.target\n')
    return units


class ManagedMicrophone:
    def __init__(self, snapshot, *, env=None, timeout=5):
        self.snapshot = snapshot
        self.env = dict(external_process_env() if env is None else env)
        self.timeout = timeout

    @staticmethod
    def _ready(data):
        try:
            parse_graph(data)
            parse_graph(data, direct=True)
            return True
        except RuntimeError:
            return False

    def _run(self, *args):
        try:
            return subprocess.run([self.systemctl, '--user', *args], env=self.env,
                capture_output=True, text=True, check=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError('managed_setup_service_failed') from exc

    def _validate_units(self, directory, units):
        for name, content in units.items():
            path = directory/name
            if path.is_symlink() or (path.exists() and path.read_text() != content):
                raise RuntimeError('managed_setup_conflict')
            result = self._run('show', '--property=LoadState', '--property=FragmentPath',
                               '--property=DropInPaths', name)
            properties = dict(line.split('=', 1) for line in result.splitlines() if '=' in line)
            if properties.get('LoadState') not in ('loaded', 'not-found'):
                raise RuntimeError('managed_setup_conflict')
            fragment = properties.get('FragmentPath')
            if properties.get('DropInPaths') or (fragment and Path(fragment) != path):
                raise RuntimeError('managed_setup_conflict')

    def ensure(self):
        if not sys.platform.startswith('linux'):
            raise RuntimeError('managed_route_linux_only')
        if self._ready(self.snapshot()):
            return  # Manual daemon-owned routes need neither systemd nor files.
        # Never accidentally provision the host manager for a private/test server.
        if (self.env.get('PIPEWIRE_REMOTE', 'pipewire-0') != 'pipewire-0'
                or self.env.get('PIPEWIRE_RUNTIME_DIR') not in (None, self.env.get('XDG_RUNTIME_DIR'))):
            raise RuntimeError('managed_setup_custom_remote')
        self.systemctl = shutil.which('systemctl', path=self.env.get('PATH'))
        binary = shutil.which('pw-loopback', path=self.env.get('PATH'))
        if not self.systemctl or not binary:
            raise RuntimeError('managed_setup_tools_missing')
        runtime = Path(self.env.get('XDG_RUNTIME_DIR', ''))
        if not runtime.is_absolute() or not runtime.is_dir():
            raise RuntimeError('managed_setup_session_unavailable')
        config = Path(self.env.get('XDG_CONFIG_HOME', ''))
        if not config.is_absolute():
            config = Path.home()/'.config'
        for base in (config, Path('/etc')):
            if (base/'pipewire/pipewire.conf.d/90-vrct-managed.conf').exists():
                raise RuntimeError('managed_setup_manual_config_pending')
        directory = config/'systemd/user'
        units = service_units(binary)
        try:
            import fcntl
            fd = os.open(runtime/'vrct-managed-setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a') as lock:
                deadline = time.monotonic() + self.timeout
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError('managed_setup_busy')
                        time.sleep(.05)
                data = self.snapshot()
                if self._ready(data):
                    return
                nodes = [n.get('info', {}).get('props', {}) for n in data
                         if n.get('type') == 'PipeWire:Interface:Node']
                existing = [p for p in nodes if p.get('node.name', '').startswith('vrct.managed.')]
                names = [p['node.name'] for p in existing]
                # An interrupted owned install may be retried; other partial or
                # duplicate routes are ambiguous and must not be supplemented.
                if (len(names) != len(set(names)) or any(p.get('vrct.managed.owner') != OWNER for p in existing)
                        or (existing and not all((directory/n).is_file() for n in units))):
                    raise RuntimeError('managed_setup_conflict')
                self._validate_units(directory, units)
                directory.mkdir(parents=True, exist_ok=True)
                for name, content in units.items():
                    path = directory/name
                    if not path.exists():
                        # Exclusive creation never overwrites an administrator/user file.
                        with path.open('x', encoding='utf-8') as target:
                            target.write(content)
                            target.flush()
                            os.fsync(target.fileno())
                self._run('daemon-reload')
                self._validate_units(directory, units)
                self._run('enable', '--now', *units)
                deadline = time.monotonic() + self.timeout
                while True:
                    if self._ready(self.snapshot()):
                        return
                    if time.monotonic() >= deadline:
                        raise RuntimeError('managed_setup_timeout')
                    time.sleep(.05)
        except OSError as exc:
            raise RuntimeError('managed_setup_files_unavailable') from exc
