"""Build the Linux PipeWire control helper using the installed system library."""
from pathlib import Path
import shlex
import subprocess
import sys


def main():
    if not sys.platform.startswith('linux'):
        raise SystemExit('Linux required')
    root = Path(__file__).resolve().parents[1]
    destination = root / 'build' / 'vrct-voice-gate'
    destination.parent.mkdir(exist_ok=True)
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libpipewire-0.3'], text=True)
    subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(root / 'native/voice-gate/main.c'), '-o', str(destination), *shlex.split(flags)], check=True)
    print(destination)


if __name__ == '__main__':
    main()
