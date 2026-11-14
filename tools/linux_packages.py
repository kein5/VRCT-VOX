"""Build .deb and .rpm packages from a checked Linux candidate directory (VRCT-VOX/).

    python tools/linux_packages.py --candidate build/linux/candidate/VRCT-VOX --output-dir build/linux/artifacts

The packages hold the same files as the release tar.gz. They install them read-only under
/opt/vrct-vox, add /usr/bin/vrct-vox, a desktop entry, an icon and the license notices, and
declare what the tar.gz needs from the host: glibc, GTK 3 and WebKitGTK 4.1 (with what they pull
in), and for the Vulkan variant the Vulkan loader: speech.cpp loads libvulkan.so.1 from the system,
not the copy in _internal. The bundle carries libpipewire and OpenSSL itself (checked with readelf on
the 0.2.0 tar.gz). The PipeWire tools are recommended: managed audio routing runs them, and so are
the Mesa Vulkan drivers for the Vulkan variant. The lowest glibc comes from the candidate's
build-manifest.json. Settings and models stay in the user's XDG folders.

`package-manager` beside the binary names the package format, so the app knows that updates
come from the package manager and never replaces itself (self-update, 0.3.0).
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'vrct-vox'
PREFIX = Path('opt/vrct-vox')
SUMMARY = 'Speech recognition, speech, voice conversion and translated chat for VRChat'
DESCRIPTION = ('VRCT-VOX translates and speaks your chat and voice in VRChat, with speech '
               'recognition, text to speech, voice conversion and chat reading.')
HOMEPAGE = 'https://github.com/kein5/VRCT-VOX'
# Debian and Fedora names of what the tar.gz needs from the host.
DEB_DEPENDS = ['libwebkit2gtk-4.1-0', 'libgtk-3-0t64 | libgtk-3-0']
DEB_RECOMMENDS = ['pipewire-bin']
RPM_REQUIRES = ['webkit2gtk4.1', 'gtk3']
RPM_RECOMMENDS = ['pipewire-utils']
# Only the Vulkan variant: the loader is required, a driver for the GPU is recommended.
VULKAN = {'deb': ('libvulkan1', 'mesa-vulkan-drivers'), 'rpm': ('vulkan-loader', 'mesa-vulkan-drivers')}
WRAPPER = '#!/bin/sh\nexec /opt/vrct-vox/vrct-vox "$@"\n'
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(beta\.[1-9][0-9]*))?')


def package_version(version):
    """1.2.3-beta.4 -> 1.2.3~beta.4: dpkg and rpm sort a tilde before the release itself."""
    match = VERSION.fullmatch(version)
    if not match:
        raise ValueError('Expected a version X.Y.Z or X.Y.Z-beta.N')
    return version.replace('-', '~', 1)


def build_facts(candidate):
    """(version, variant, lowest glibc) from the candidate's build-manifest.json."""
    manifest = json.loads((Path(candidate) / 'build-manifest.json').read_text(encoding='utf-8'))
    glibc = [tuple(int(part) for part in value.removeprefix('GLIBC_').split('.'))
             for row in manifest['files'] for value in row.get('elf_versions', ())
             if re.fullmatch(r'GLIBC_[0-9]+(?:\.[0-9]+)+', value)]
    if not glibc:
        raise ValueError('The candidate records no glibc requirement')
    if manifest.get('variant') not in ('linux-x64-vulkan', 'linux-x64-cpu'):
        raise ValueError('Unknown engine variant')
    return manifest['version'], manifest['variant'], '.'.join(map(str, max(glibc)))


def requirements(kind, variant, glibc):
    """(required, recommended) package names."""
    if kind == 'deb':
        required, recommended = [f'libc6 (>= {glibc})', *DEB_DEPENDS], [*DEB_RECOMMENDS]
    else:
        required, recommended = [f'glibc >= {glibc}', *RPM_REQUIRES], [*RPM_RECOMMENDS]
    if variant == 'linux-x64-vulkan':
        loader, driver = VULKAN[kind]
        required.append(loader)
        recommended.append(driver)
    return required, recommended


def _link_or_copy(source, destination):
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def stage(candidate, root, kind):
    """The installed tree under `root`: /opt/vrct-vox and the files /usr needs."""
    candidate, root = Path(candidate), Path(root)
    if not (candidate / 'vrct-vox').is_file() or not (candidate / 'build-manifest.json').is_file():
        raise ValueError('Not a Linux candidate directory')
    # Hard links, not copies: the runner's disk is nearly full with the tar.gz and the AppImage.
    shutil.copytree(candidate, root / PREFIX, symlinks=True, copy_function=_link_or_copy)
    (root / PREFIX / 'package-manager').write_text(kind + '\n', encoding='ascii')
    files = {
        'usr/bin/vrct-vox': (WRAPPER.encode(), 0o755),
        'usr/share/applications/vrct-vox.desktop': ((ROOT / 'packaging/appimage/vrct-vox.desktop').read_bytes(), 0o644),
        'usr/share/icons/hicolor/256x256/apps/vrct-vox.png': ((ROOT / 'src-tauri/icons/128x128@2x.png').read_bytes(), 0o644),
        'usr/share/doc/vrct-vox/copyright': ((ROOT / 'LICENSE').read_bytes(), 0o644),
        'usr/share/doc/vrct-vox/NOTICE.md': ((ROOT / 'NOTICE.md').read_bytes(), 0o644),
    }
    for relative, (data, mode) in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
    for path in [root, *root.rglob('*')]:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
    return root


def installed_kib(root):
    return sum(path.lstat().st_size for path in Path(root).rglob('*') if not path.is_dir()) // 1024 + 1


def deb_control(version, variant, glibc, size_kib):
    required, recommended = requirements('deb', variant, glibc)
    return '\n'.join([
        f'Package: {NAME}',
        f'Version: {package_version(version)}',
        'Architecture: amd64',
        'Maintainer: VRCT-VOX maintainers <https://github.com/kein5/VRCT-VOX/issues>',
        f'Installed-Size: {size_kib}',
        f'Depends: {", ".join(required)}',
        f'Recommends: {", ".join(recommended)}',
        'Section: sound',
        'Priority: optional',
        f'Homepage: {HOMEPAGE}',
        f'Description: {SUMMARY}',
        f' {DESCRIPTION}',
        '',
    ])


def rpm_spec(version, variant, glibc, staged):
    required, recommended = requirements('rpm', variant, glibc)
    requires = '\n'.join([*(f'Requires: {row}' for row in required),
                          *(f'Recommends: {row}' for row in recommended)])
    return f"""# Prebuilt files from a checked candidate: nothing is compiled, stripped or rewritten here.
%global debug_package %{{nil}}
%global __os_install_post %{{nil}}
%global _build_id_links none
Name: {NAME}
Version: {package_version(version)}
Release: 1
Summary: {SUMMARY}
License: MIT AND LicenseRef-VRCT-VOX-bundled
URL: {HOMEPAGE}
ExclusiveArch: x86_64
AutoReqProv: no
{requires}

%description
{DESCRIPTION}
The bundled components and their licenses are listed in /usr/share/doc/vrct-vox/NOTICE.md.

%install
mkdir -p %{{buildroot}}
cp -al '{staged}/.' %{{buildroot}}/

%files
/opt/vrct-vox
/usr/bin/vrct-vox
/usr/share/applications/vrct-vox.desktop
/usr/share/icons/hicolor/256x256/apps/vrct-vox.png
%license /usr/share/doc/vrct-vox/copyright
%doc /usr/share/doc/vrct-vox/NOTICE.md
"""


def run(argv, **options):
    subprocess.run([str(value) for value in argv], check=True, **options)


def build_deb(candidate, output, work):
    version, variant, glibc = build_facts(candidate)
    root = stage(candidate, Path(work) / 'deb', 'deb')
    (root / 'DEBIAN').mkdir()
    (root / 'DEBIAN/control').write_text(deb_control(version, variant, glibc, installed_kib(root)), encoding='utf-8')
    run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', root, output])
    return output


def build_rpm(candidate, output, work):
    version, variant, glibc = build_facts(candidate)
    work = Path(work)
    staged = stage(candidate, work / 'rpm-root', 'rpm')
    top = work / 'rpmbuild'
    (top / 'SPECS').mkdir(parents=True)
    spec = top / 'SPECS/vrct-vox.spec'
    spec.write_text(rpm_spec(version, variant, glibc, staged.resolve()), encoding='utf-8')
    run(['rpmbuild', '-bb', '--define', f'_topdir {top.resolve()}', '--target', 'x86_64', spec])
    built = list((top / 'RPMS/x86_64').glob(f'{NAME}-*.x86_64.rpm'))
    if len(built) != 1:
        raise RuntimeError('rpmbuild did not produce exactly one package')
    shutil.move(built[0], output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--formats', default='deb,rpm')
    args = parser.parse_args()
    version, variant, _ = build_facts(args.candidate)
    stem = f'VRCT-VOX-{version}-{variant}-release'
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for kind in args.formats.split(','):
        builder = {'deb': build_deb, 'rpm': build_rpm}[kind]
        # Beside the candidate, so that hard links stay on one file system.
        with tempfile.TemporaryDirectory(prefix=f'vrct-{kind}-', dir=args.candidate.resolve().parent) as work:
            path = builder(args.candidate, args.output_dir / f'{stem}.{kind}', work)
        print(f'Unpublished {kind}: {path.resolve()}')


if __name__ == '__main__':
    main()
