"""Create an inspected AppImage from the Linux candidate; never publish or fetch models."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
from urllib.request import Request, urlopen

try:
    from .build_linux import prepare_work, run
    from .linux_package import RUNTIME, check_tree, inventory, normalize_modes, sha256
    from .speechcpp_bundle import verify_bundle
except ImportError:
    from build_linux import prepare_work, run
    from linux_package import RUNTIME, check_tree, inventory, normalize_modes, sha256
    from speechcpp_bundle import verify_bundle

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/voice-stack/appimage-tools.json'


def store_tool(directory, row, data):
    if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
        raise ValueError(f'AppImage tool content mismatch: {row["name"]}')
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
        partial = Path(output.name)
        output.write(data)
    try:
        os.link(partial, directory / row['name'])  # never replace a concurrent file
    finally:
        partial.unlink()


def check_tool(target, row):
    if (not target.exists() or not stat.S_ISREG(target.lstat().st_mode)
            or target.stat().st_size != row['size'] or sha256(target) != row['sha256']):
        raise ValueError(f'AppImage tool missing or hash mismatch: {target}')


def verify_tools(directory, *, download=False):
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('tool directory must not be a symlink')
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for row in json.loads(MANIFEST.read_text())['tools']:
        target = directory / row['name']
        if not os.path.lexists(target) and download:
            request = Request(row['url'], headers={'User-Agent': 'VRCT-VOX-AppImage-build'})
            with urlopen(request, timeout=60) as response:
                data = response.read(row['size'] + 1)
            store_tool(directory, row, data)
        check_tool(target, row)
        if 'extract' in row:
            extracted = row['extract']
            binary = directory / extracted['name']
            if not os.path.lexists(binary):
                with tarfile.open(target, 'r:gz') as archive:
                    members = [m for m in archive if m.name == extracted['member']]
                    if len(members) != 1 or not members[0].isfile() or members[0].size != extracted['size']:
                        raise ValueError('AppImage tool archive member invalid')
                    with archive.extractfile(members[0]) as source:
                        store_tool(directory, extracted, source.read(extracted['size'] + 1))
            check_tool(binary, extracted)
            target, row = binary, extracted
        target.chmod(0o755)
        result[row['name']] = target.resolve()
    return result


def verify_runtime(image, runtime, *, digest_offset=None):
    expected = bytearray(Path(runtime).read_bytes())
    offset = json.loads(MANIFEST.read_text())['runtime_digest_md5']['offset'] if digest_offset is None else digest_offset
    if offset < 0 or offset + 16 > len(expected):
        raise ValueError('invalid runtime digest section')
    with Path(image).open('rb') as source:
        actual = bytearray(source.read(len(expected)))
        squashfs = source.read(4)
    if len(actual) != len(expected) or squashfs != b'hsqs':
        raise ValueError('AppImage runtime/SquashFS boundary invalid')
    expected[offset:offset + 16] = actual[offset:offset + 16] = bytes(16)
    if actual != expected:
        raise ValueError('AppImage runtime prefix mismatch')


def install_payload(candidate, appdir):
    target = Path(appdir) / 'usr/lib/vrct-vox'
    target.mkdir(parents=True)
    for source in Path(candidate).iterdir():
        if source.name == 'vrct-vox':
            continue  # GUI already deployed/patched separately by linuxdeploy
        if source.is_dir():
            shutil.copytree(source, target / source.name, symlinks=True)
        else:
            shutil.copy2(source, target / source.name, follow_symlinks=False)


def install_launchers(appdir):
    appdir = Path(appdir)
    (appdir / 'AppRun').rename(appdir / 'AppRun.gui')
    if not os.path.lexists(appdir / '.DirIcon'):
        (appdir / '.DirIcon').symlink_to('vrct-vox.png')
    for name, target in [('AppRun', appdir / 'AppRun'), ('sidecar', appdir / 'usr/bin/vrct-vox-sidecar')]:
        shutil.copyfile(ROOT / 'packaging/appimage' / name, target)
        target.chmod(0o755)


def check_appdir(appdir):
    appdir = Path(appdir)
    check_tree(appdir, allow_directory_links=True)
    for name in ('AppRun', 'AppRun.gui', 'vrct-vox.desktop', 'vrct-vox.png', '.DirIcon',
                 'usr/bin/vrct-vox', 'usr/bin/vrct-vox-sidecar'):
        if not (appdir / name).is_file():
            raise ValueError(f'missing AppDir component: {name}')
    for name in RUNTIME:
        if name != 'vrct-vox' and not (appdir / 'usr/lib/vrct-vox' / name).is_file():
            raise ValueError(f'missing AppDir backend: {name}')
    verify_bundle(appdir / 'usr/lib/vrct-vox/_internal/build/speechcpp')


def inspect_image(image, runtime, work):
    """The exact approved runtime may extract its filesystem; never invoke AppRun here."""
    verify_runtime(image, runtime)
    with tempfile.TemporaryDirectory(dir=work, prefix='inspect-') as directory:
        env = dict(os.environ)
        env.pop('APPIMAGE_EXTRACT_AND_RUN', None)
        with (Path(work) / 'extract.log').open('w') as log:
            subprocess.run([str(Path(image).resolve()), '--appimage-extract'], cwd=directory,
                           env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        root = Path(directory) / 'squashfs-root'
        check_appdir(root)
        return inventory(root)


def webkit_helpers(appdir):
    bases = [Path(p) / 'webkit2gtk-4.1' for p in
             ('/usr/lib/x86_64-linux-gnu', '/usr/libexec', '/usr/lib', '/usr/lib64')]
    for name in ('WebKitWebProcess', 'WebKitNetworkProcess', 'injected-bundle/libwebkit2gtkinjectedbundle.so'):
        source = next((p / name for p in bases if (p / name).is_file()), None)
        if source is None:
            raise ValueError(f'WebKitGTK 4.1 helper missing: {name}')
        target = Path(appdir) / source.relative_to('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, default=ROOT / 'build/linux/candidate/VRCT-VOX')
    parser.add_argument('--work-dir', type=Path, default=ROOT / 'build/appimage')
    parser.add_argument('--tools-dir', type=Path, default=ROOT / 'build/appimage-tools')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/linux/artifacts')
    parser.add_argument('--download-tools', action='store_true')
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    check_tree(candidate, require_runtime=True)
    verify_bundle(candidate / '_internal/build/speechcpp')
    tools = verify_tools(args.tools_dir, download=args.download_tools)
    work = prepare_work(args.work_dir)
    appdir = work / 'VRCT-VOX.AppDir'
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / 'usr/bin').mkdir(parents=True)
    gui = appdir / 'usr/bin/vrct-vox'
    shutil.copy2(candidate / 'vrct-vox', gui)
    icon = appdir / 'usr/share/icons/hicolor/256x256/apps/vrct-vox.png'
    icon.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / 'src-tauri/icons/128x128@2x.png', icon)
    desktop = ROOT / 'packaging/appimage/vrct-vox.desktop'
    run(['desktop-file-validate', desktop])
    webkit_helpers(appdir)
    env = dict(os.environ, APPIMAGE_EXTRACT_AND_RUN='1', DEPLOY_GTK_VERSION='3',
               NO_STRIP='1', ARCH='x86_64', PATCHELF=str(tools['patchelf']),
               PATH=str(args.tools_dir.resolve()) + os.pathsep + os.environ['PATH'])
    run([tools['linuxdeploy-x86_64.AppImage'], '--appdir', appdir, '--executable', gui,
         '--desktop-file', desktop, '--icon-file', icon, '--plugin', 'gtk'], env=env)
    # Nothing that rewrites ELF bytes may run over the frozen backend.
    install_payload(candidate, appdir)
    install_launchers(appdir)
    shutil.copytree(ROOT / 'licenses/appimage', appdir / 'usr/share/licenses/vrct-vox-appimage')
    normalize_modes(appdir)
    check_appdir(appdir)
    before = inventory(appdir)
    source = json.loads((candidate / 'build-manifest.json').read_text())
    name = f'VRCT-VOX-{source["version"]}-{source["variant"]}-{source["profile"]}.AppImage'
    output = work / name
    output.unlink(missing_ok=True)
    run([tools['appimagetool-x86_64.AppImage'], '--runtime-file', tools['runtime-x86_64'],
         '--no-appstream', '--comp', 'zstd', '--mksquashfs-opt', '-processors', '--mksquashfs-opt', '4',
         appdir, output], env=env)
    after = inspect_image(output, tools['runtime-x86_64'], work)
    if before != after:
        raise ValueError('AppImage extraction differs from inspected AppDir')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / name
    shutil.copy2(output, destination)
    destination.chmod(0o755)
    digest = sha256(destination)
    destination.with_name(name + '.sha256').write_text(f'{digest}  {name}\n')
    report = {'schema': 1, 'sha256': digest, 'bytes': destination.stat().st_size,
              'source_candidate': source, 'tools': json.loads(MANIFEST.read_text()), 'files': after,
              'limits': ['Host glibc/kernel/GPU drivers/PipeWire remain requirements.',
                         'Not a final dependency license/SBOM/security clearance.']}
    destination.with_name(name + '.manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'Unpublished inspected AppImage: {destination.resolve()}')


if __name__ == '__main__':
    main()
