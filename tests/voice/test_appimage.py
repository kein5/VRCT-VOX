"""Exercise packaging boundaries, not merely generated launcher text."""
import json
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux AppImage launchers')


@pytest.mark.parametrize('library_path', [None, '', '/host/libs with spaces'])
@pytest.mark.parametrize('host_data', [None, '/host/share'])
def test_gui_environment_does_not_reach_sidecar(tmp_path, library_path, host_data):
    from tools.build_appimage import install_launchers
    appdir = tmp_path / 'bundle with spaces.AppDir'
    (appdir / 'usr/bin').mkdir(parents=True)
    payload = appdir / 'usr/lib/vrct-tts'
    payload.mkdir(parents=True)
    (appdir / 'AppRun').write_text('''#!/bin/sh
. "$APPDIR/apprun-hooks/test.sh"
test "$PWD" = "$APPDIR/usr" || exit 21
test "$GUI_HOOK_LOADED" = yes || exit 22
test "$GUI_HOOK_COUNT" = 1 || exit 24
case "$LD_LIBRARY_PATH" in "$APPDIR/usr/lib"*) ;; *) exit 23 ;; esac
export LD_LIBRARY_PATH="$APPDIR/usr/lib"
export GIO_EXTRA_MODULES="$APPDIR/usr/lib/gio"
export XDG_DATA_DIRS="$APPDIR/usr/share"
export LD_LIBRARY_PATH_ORIG=/wrong/gui
exec "$APPDIR/usr/bin/vrct-tts-sidecar" "$@"
''')
    (appdir / 'AppRun').chmod(0o755)
    (appdir / 'apprun-hooks').mkdir()
    (appdir / 'apprun-hooks/test.sh').write_text('export GUI_HOOK_LOADED=yes\nexport GUI_HOOK_COUNT=$((${GUI_HOOK_COUNT:-0}+1))\nexport XDG_DATA_DIRS="$APPDIR/usr/share:$XDG_DATA_DIRS"\n')
    (appdir / 'vrct-tts.png').write_bytes(b'icon')
    # A real subprocess observes the environment after both launchers.
    target = payload / 'vrct-tts-sidecar'
    target.write_text(f'#!{sys.executable}\nimport json,os,sys\nprint(json.dumps({{"args":sys.argv[1:],"ld":os.environ.get("LD_LIBRARY_PATH"),"gio":os.environ.get("GIO_EXTRA_MODULES"),"xdg":os.environ.get("XDG_DATA_DIRS"),"orig":os.environ.get("LD_LIBRARY_PATH_ORIG")}}))\n')
    target.chmod(0o755)
    install_launchers(appdir)
    assert (appdir / '.DirIcon').read_bytes() == b'icon'
    env = dict(os.environ, APPDIR='/wrong', GIO_EXTRA_MODULES='/host/gio')
    env.pop('GUI_HOOK_COUNT', None)
    env.pop('XDG_DATA_DIRS', None)
    if host_data is not None:
        env['XDG_DATA_DIRS'] = host_data
    env.pop('LD_LIBRARY_PATH', None)
    if library_path is not None:
        env['LD_LIBRARY_PATH'] = library_path
    result = subprocess.run([str(appdir / 'AppRun'), 'two words', '$(not a command)', ''],
                            env=env, cwd=tmp_path, check=True, text=True, capture_output=True)
    assert json.loads(result.stdout) == {'args': ['two words', '$(not a command)', ''],
                                        'ld': library_path, 'gio': '/host/gio', 'xdg': host_data, 'orig': None}


def test_directory_links_require_explicit_appdir_mode(tmp_path):
    from tools.linux_package import check_tree
    (tmp_path / 'lib').mkdir()
    (tmp_path / 'lib/library.so').write_bytes(b'library')
    (tmp_path / 'lib64').symlink_to('lib', target_is_directory=True)
    with pytest.raises(ValueError):
        check_tree(tmp_path)
    check_tree(tmp_path, allow_directory_links=True)


@pytest.mark.parametrize('target', ['../outside', 'missing', 'cycle'])
def test_appdir_mode_still_rejects_outside_broken_or_cyclic_links(tmp_path, target):
    from tools.linux_package import check_tree
    root = tmp_path / 'AppDir'
    root.mkdir()
    (tmp_path / 'outside').mkdir()
    (root / 'cycle').symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        check_tree(root, allow_directory_links=True)


def test_runtime_comparison_allows_only_embedded_digest(tmp_path):
    from tools.build_appimage import verify_runtime
    runtime = tmp_path / 'runtime'
    image = tmp_path / 'program.AppImage'
    runtime.write_bytes(b'\x7fELF' + bytes(96))
    data = bytearray(runtime.read_bytes())
    data[64:80] = b'0123456789abcdef'
    image.write_bytes(data + b'hsqs payload')
    verify_runtime(image, runtime, digest_offset=64)
    data[20] = 1  # Executable prefix corruption is never a metadata exception.
    image.write_bytes(data + b'hsqs payload')
    with pytest.raises(ValueError, match='runtime'):
        verify_runtime(image, runtime, digest_offset=64)


def test_short_runtime_and_missing_squashfs_are_rejected(tmp_path):
    from tools.build_appimage import verify_runtime
    runtime, image = tmp_path / 'runtime', tmp_path / 'image'
    runtime.write_bytes(bytes(100))
    for data in (bytes(40), bytes(100) + b'nope'):
        image.write_bytes(data)
        with pytest.raises(ValueError):
            verify_runtime(image, runtime, digest_offset=64)


def test_wrong_tool_hash_is_rejected_before_execution(tmp_path):
    from tools.build_appimage import verify_tools
    manifest = json.loads((Path(__file__).resolve().parents[2] / 'docs/voice-stack/appimage-tools.json').read_text())
    for row in manifest['tools']:
        (tmp_path / row['name']).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='tool'):
        verify_tools(tmp_path)


@pytest.mark.parametrize('corruption', [None, 'hash', 'link'])
def test_pinned_archive_extracts_only_verified_tool(tmp_path, monkeypatch, corruption):
    from tools import build_appimage
    payload = b'fixed binary'
    archive = tmp_path / 'tool.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        member = tarfile.TarInfo('./bin/tool')
        member.size = len(payload)
        if corruption == 'link':
            member.type, member.linkname, member.size = tarfile.SYMTYPE, '/host/executable', 0
        output.addfile(member, io.BytesIO(payload))
        extra = tarfile.TarInfo('../unrequested')
        extra.size = 4
        output.addfile(extra, io.BytesIO(b'omit'))
    manifest = tmp_path / 'tools.json'
    manifest.write_text(json.dumps({'tools': [{
        'name': archive.name, 'size': archive.stat().st_size,
        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'extract': {'name': 'tool', 'member': './bin/tool', 'size': len(payload),
                    'sha256': hashlib.sha256(payload).hexdigest() if corruption != 'hash' else '0' * 64}
    }]}))
    monkeypatch.setattr(build_appimage, 'MANIFEST', manifest)
    if corruption:
        with pytest.raises(ValueError, match='tool'):
            build_appimage.verify_tools(tmp_path)
        assert not (tmp_path / 'tool').exists()
    else:
        assert build_appimage.verify_tools(tmp_path)['tool'].read_bytes() == payload
        (tmp_path / 'tool').write_bytes(b'corrupt')
        with pytest.raises(ValueError, match='tool'):
            build_appimage.verify_tools(tmp_path)
    assert not (tmp_path.parent / 'unrequested').exists()


def test_backend_payload_is_copied_without_rewriting(tmp_path):
    from tools.build_appimage import install_payload
    candidate, appdir = tmp_path / 'candidate', tmp_path / 'AppDir'
    (candidate / '_internal/build/speechcpp').mkdir(parents=True)
    (candidate / 'vrct-tts').write_bytes(b'gui')
    (candidate / 'vrct-tts-sidecar').write_bytes(b'frozen')
    (candidate / '_internal/build/speechcpp/speech').write_bytes(b'exact pinned engine')
    (candidate / '_internal/lib.so').symlink_to('build/speechcpp/speech')
    install_payload(candidate, appdir)
    target = appdir / 'usr/lib/vrct-tts'
    assert (target / '_internal/build/speechcpp/speech').read_bytes() == b'exact pinned engine'
    assert (target / '_internal/lib.so').is_symlink()
    assert not (target / 'vrct-tts').exists(), 'do not include a duplicate unpatched GUI'
    assert (candidate / '_internal/build/speechcpp/speech').read_bytes() == b'exact pinned engine'


def test_webdriver_matches_only_payload_of_launched_appimage(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'platform'))
    from native_webdriver import matches_launched_app
    image = '/tmp/My App.AppImage'
    executable = '/tmp/.mount_test/usr/bin/vrct-tts'
    env = {'APPIMAGE': image, 'APPDIR': '/tmp/.mount_test'}
    assert matches_launched_app(executable, env, image, appimage=True)
    assert not matches_launched_app(image, {}, image, appimage=True), 'extract runtime waits for GUI exit'
    assert not matches_launched_app(executable, dict(env, APPIMAGE='/tmp/other.AppImage'), image, appimage=True)
    assert not matches_launched_app('/tmp/unrelated/vrct-tts', env, image, appimage=True)
    assert not matches_launched_app(executable, {}, image, appimage=True)
    assert matches_launched_app('/tmp/app/vrct-tts', {}, '/tmp/app/vrct-tts')
