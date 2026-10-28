"""Build the Linux PipeWire control helper using the installed system library."""
from pathlib import Path
import shlex
import subprocess
import sys


def main():
    if not sys.platform.startswith('linux'):
        raise SystemExit('Linux required')
    root = Path(__file__).resolve().parents[1]
    (root / 'build').mkdir(exist_ok=True)
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libpipewire-0.3'], text=True)
    for name, extra in [('voice-gate', shlex.split(flags)), ('source-bridge', []), ('asr-capture', shlex.split(flags) + ['-lm'])]:
        destination = root / 'build' / f'vrct-{name}'
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(root / 'native' / name / 'main.c'), '-o', str(destination), *extra], check=True)
        print(destination)


if __name__ == '__main__':
    main()
