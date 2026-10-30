"""Build the Linux PipeWire control helper using the installed system library."""
import argparse
from pathlib import Path
import shlex
import subprocess
import sys


def main():
    if not sys.platform.startswith('linux'):
        raise SystemExit('Linux required')
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=root / 'build')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libpipewire-0.3'], text=True)
    for name, extra in [('voice-gate', shlex.split(flags)), ('source-bridge', []), ('vc-worker', []), ('asr-capture', shlex.split(flags) + ['-lm'])]:
        destination = args.output_dir / f'vrct-{name}'
        subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(root / 'native' / name / 'main.c'), '-o', str(destination), *extra], check=True)
        print(destination)


if __name__ == '__main__':
    main()
