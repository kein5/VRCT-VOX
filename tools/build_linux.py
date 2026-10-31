"""Build an unpublished Linux x86_64 tar.gz candidate with uv and locked dependencies.

Never modifies the development sidecar. No models are fetched by this tool.
System dependencies are documented in docs/voice-stack/linux-build-pipeline.md.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

try:
    from .linux_package import check_tree, inventory, normalize_modes, pack
    from .speechcpp_bundle import VARIANTS, stage_bundle, fetch_archive, load_manifest, verify_bundle
except ImportError:
    from linux_package import check_tree, inventory, normalize_modes, pack
    from speechcpp_bundle import VARIANTS, stage_bundle, fetch_archive, load_manifest, verify_bundle

ROOT = Path(__file__).resolve().parents[1]


def prepare_work(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('dedicated build directory must not be a symlink')
    work = path.resolve()
    marker = work / '.vrct-linux-build'
    if work == ROOT or work in ROOT.parents or work.is_relative_to(ROOT / 'src-tauri'):
        raise ValueError('choose a dedicated build directory')
    if work.exists() and any(work.iterdir()) and (not marker.is_file() or marker.read_text() != 'VRCT-VOX Linux staging v1\n'):
        raise ValueError('refusing an existing nonempty directory: choose a dedicated build directory')
    work.mkdir(parents=True, exist_ok=True)
    marker.write_text('VRCT-VOX Linux staging v1\n')
    return work


def run(argv, *, cwd=ROOT, env=None):
    print('+ ' + ' '.join(map(str, argv)), flush=True)
    subprocess.run(list(map(str, argv)), cwd=cwd, env=env, check=True)


def environment_resources(destination):
    """Run inside the build venv. Copy available attribution, record missing notices."""
    destination = Path(destination)
    rows = []
    for package in sorted(importlib.metadata.distributions(), key=lambda p: p.metadata['Name'].lower()):
        name = package.metadata['Name']
        row = {'name': name, 'version': package.version,
               'license': package.metadata.get('License-Expression') or package.metadata.get('License'),
               'notice_files': []}
        for file in package.files or []:
            if '.dist-info/' not in str(file) and '.egg-info/' not in str(file):
                continue
            if not any(part.lower().startswith(('license', 'copying', 'notice', 'authors')) for part in file.parts):
                continue
            source = Path(package.locate_file(file))
            if not source.is_file():
                continue
            # Preserve relative nested names; wheel RECORDs must stay within the package.
            if '..' in file.parts or file.is_absolute():
                raise ValueError(f'Unsafe package metadata path: {file}')
            target = destination / 'licenses/python' / f'{name}-{package.version}' / file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            row['notice_files'].append(target.relative_to(destination).as_posix())
        rows.append(row)
    (destination / 'python-environment.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')


def copy_adapters(resources):
    for engine in ('rvc', 'seed_vc'):
        source = ROOT / 'integrations' / engine
        for file in source.iterdir():
            if file.is_file() and (file.suffix == '.py' or file.name.startswith(('LICENSE', 'README'))):
                target = resources / 'integrations' / engine / file.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
    # External inference interpreters cannot read the frozen sidecar's PYZ.
    # Ship only their small, dependency-free contract modules as ordinary files.
    for name in ('__init__.py', 'voice_conversion/__init__.py',
                 'voice_conversion/protocol.py', 'voice_conversion/settings.py'):
        source = ROOT / 'src-python/models' / name
        target = resources / 'src-python/models' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def tauri_workspace(work, frozen):
    workspace = work / 'workspace'
    tauri = workspace / 'src-tauri'
    tauri.mkdir(parents=True, exist_ok=True)
    for name in ('Cargo.toml', 'Cargo.lock', 'build.rs', 'tauri.conf.json'):
        shutil.copyfile(ROOT / 'src-tauri' / name, tauri / name)
    for name in ('src', 'icons', 'capabilities'):
        if (tauri / name).exists():
            shutil.rmtree(tauri / name)
        shutil.copytree(ROOT / 'src-tauri' / name, tauri / name)
    shutil.copyfile(ROOT / 'LICENSE', workspace / 'LICENSE')
    (workspace / 'tools').mkdir(exist_ok=True)
    for name in ('check_voice_distribution.py', 'distribution_policy.py', 'linux_package.py'):
        shutil.copyfile(ROOT / 'tools' / name, workspace / 'tools' / name)
    if (workspace / 'dist').exists():
        shutil.rmtree(workspace / 'dist')
    shutil.copytree(ROOT / 'dist', workspace / 'dist')
    binary = tauri / 'bin'
    if binary.exists():
        shutil.rmtree(binary)
    binary.mkdir()
    shutil.copy2(frozen / 'vrct-vox-sidecar', binary / 'vrct-vox-sidecar-x86_64-unknown-linux-gnu')
    shutil.copytree(frozen / '_internal', binary / '_internal', symlinks=True)
    config = json.loads((tauri / 'tauri.conf.json').read_text())
    config['bundle']['targets'] = []
    config['bundle'].pop('windows', None)
    (tauri / 'tauri.conf.json').write_text(json.dumps(config, indent=2))
    return workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, default=ROOT / 'build/linux')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/linux/artifacts')
    parser.add_argument('--python', default='3.11', help='uv interpreter selector for the isolated build venv')
    parser.add_argument('--variant', choices=VARIANTS, default='linux-x64-vulkan')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--speech-archive', type=Path)
    source.add_argument('--download-speech', action='store_true', help='fetch only the pinned engine binary, never weights')
    parser.add_argument('--profile', choices=('debug', 'release'), default='release')
    parser.add_argument('--backend-only', action='store_true', help='freeze and inspect only; no distributable is produced')
    parser.add_argument('--offline', action='store_true', help='use cached uv/npm/Cargo dependencies')
    parser.add_argument('--appimage', action='store_true', help='also package/inspect an AppImage candidate')
    parser.add_argument('--download-appimage-tools', action='store_true', help='fetch pinned build tools for --appimage')
    parser.add_argument('--collect-environment', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.collect_environment:
        environment_resources(args.collect_environment)
        return
    if sys.platform != 'linux' or platform.machine() not in ('x86_64', 'AMD64'):
        parser.error('Linux x86_64 required (no cross compilation)')
    if not (args.speech_archive or args.download_speech):
        parser.error('--speech-archive or explicit --download-speech is required')
    work = prepare_work(args.work_dir)
    venv = work / 'venv'
    python = venv / 'bin/python'
    uv = ['uv', '--offline'] if args.offline else ['uv']
    if not python.exists():
        run([*uv, 'venv', '--python', args.python, venv])
    run([*uv, 'pip', 'sync', '--python', python, ROOT / 'requirements-linux-build.lock'])
    run([python, '-c', 'import sys; assert sys.version_info[:2] == (3, 11), "Python 3.11 required"'])
    resources = work / 'resources'
    if resources.exists():
        shutil.rmtree(resources)
    resources.mkdir()
    run([sys.executable, ROOT / 'tools/build_voice_gate.py', '--output-dir', resources / 'build'])
    archive = args.speech_archive.resolve() if args.speech_archive else work / f'speech-{args.variant}.zip'
    manifest = load_manifest()
    if args.download_speech and not archive.exists():
        fetch_archive(manifest['assets'][args.variant], archive)
    stage_bundle(archive, resources / 'build/speechcpp', manifest['assets'][args.variant])
    verify_bundle(resources / 'build/speechcpp')
    copy_adapters(resources)
    shutil.copytree(ROOT / 'config/pipewire', resources / 'config/pipewire')
    (resources / 'docs').mkdir()
    for name in ('local-setup-linux.md', 'licensing.md', 'linux-build-pipeline.md'):
        shutil.copyfile(ROOT / 'docs/voice-stack' / name, resources / 'docs' / name)
    run([python, Path(__file__).resolve(), '--collect-environment', resources])
    env = dict(os.environ, VRCT_LINUX_RESOURCES=str(resources), VRCT_LINUX_BUNDLE='1',
               VRCT_BUILD_PYTHON=str(python))
    run([python, '-m', 'PyInstaller', '--noconfirm', '--distpath', work / 'frozen',
         '--workpath', work / 'pyinstaller', ROOT / 'spec/backend_linux.spec'], env=env)
    frozen = work / 'frozen/backend'
    check_tree(frozen)
    if args.backend_only:
        print(f'Frozen backend ready: {frozen}')
        return
    run(['npm', 'ci', '--ignore-scripts', *(['--offline'] if args.offline else [])])
    run(['npm', 'run', 'vite-build'])
    workspace = tauri_workspace(work, frozen)
    env['CARGO_TARGET_DIR'] = str(work / 'cargo')
    env.setdefault('CARGO_BUILD_JOBS', '4')
    if args.offline:
        env['CARGO_NET_OFFLINE'] = 'true'
    # A debug candidate still embeds the production frontend, not a Vite URL.
    env['CARGO_PROFILE_DEV_DEBUG_ASSERTIONS'] = 'false'
    run([ROOT / 'node_modules/.bin/tauri', 'build', '--no-bundle',
         *(['--debug'] if args.profile == 'debug' else []), '--', '--locked'], cwd=workspace, env=env)
    candidate = work / 'candidate/VRCT-VOX'
    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.parent.mkdir(exist_ok=True)
    shutil.copytree(frozen, candidate, symlinks=True)
    shutil.copy2(work / 'cargo' / args.profile / 'vrct-vox', candidate / 'vrct-vox')
    normalize_modes(candidate)
    check_tree(candidate, require_runtime=True)
    verify_bundle(candidate / '_internal/build/speechcpp')
    version = json.loads((ROOT / 'package.json').read_text())['version']
    report = {'schema': 1, 'version': version, 'profile': args.profile, 'variant': args.variant,
              'platform': platform.platform(), 'libc': platform.libc_ver(),
              'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT)),
              'files': inventory(candidate),
              'limitations': ['Not a license clearance; review all native-library and dependency obligations before publication.',
                              'No Windows validation; Linux ABI requirements depend on the recorded build host.']}
    (candidate / 'build-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (candidate / 'build-manifest.json').chmod(0o644)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f'VRCT-VOX-{version}-{args.variant}-{args.profile}.tar.gz'
    pack(candidate, output)
    shutil.copyfile(candidate / 'build-manifest.json', output.with_suffix('').with_suffix('.manifest.json'))
    print(f'Unpublished candidate: {output.resolve()}')
    if args.appimage:
        run([python, ROOT / 'tools/build_appimage.py', '--candidate', candidate,
             '--work-dir', work / 'appimage', '--tools-dir', work / 'appimage-tools',
             '--output-dir', args.output_dir,
             *(['--download-tools'] if args.download_appimage_tools else [])])


if __name__ == '__main__':
    main()
