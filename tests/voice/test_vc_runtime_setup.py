"""The runtime setup with fake transfers and a fake uv: consent, resume, cancel, failure.

Each setup test runs once per platform the app can set a runtime up on. Only
runtime_setup.target is replaced, so both layouts are checked on Linux and on Windows.
"""
from dataclasses import replace
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import textwrap
import time
import zipfile

import pytest

from models.model_downloads import transport
from models.voice_conversion import runtime_setup as rs

ROOT = Path(__file__).resolve().parents[2]


def source_zip(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, text in files.items():
            archive.writestr(f'engine-abc/{name}', text)
    return stream.getvalue()


def tool_archive(tool):
    """The release file in the format of its platform, with uv where the pin says."""
    stream = io.BytesIO()
    if tool.url.endswith('.zip'):
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr(tool.member, b'uv')
    else:
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            member = tarfile.TarInfo(tool.member)
            member.size = 2
            archive.addfile(member, io.BytesIO(b'uv'))
    return stream.getvalue()


PYTHON = {'win32': 'venv/Scripts/python.exe', 'linux': 'venv/bin/python'}


class Response:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def read(self, size):
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class Child:
    def __init__(self, code=0, wait_forever=False):
        self.code, self.killed, self.wait_forever = code, False, wait_forever

    def wait(self, timeout=None):
        if self.wait_forever and not self.killed:
            time.sleep(timeout or 0)
            raise subprocess.TimeoutExpired('uv', timeout)
        return -9 if self.killed else self.code

    def kill(self):
        self.killed = True


class World:
    """Serves the pinned files and records what would have run."""
    def __init__(self, tmp_path, monkeypatch, platform):
        self.platform = platform
        self.source = {'infer.py': 'pass\n'}
        self.asset = b'weights'
        monkeypatch.setattr(rs, 'target', lambda: platform)
        self.tool = tool_archive(rs.UV[platform])
        monkeypatch.setitem(rs.UV, platform, replace(rs.UV[platform], size=len(self.tool),
                                                     sha256=hashlib.sha256(self.tool).hexdigest()))
        self.uv_url = rs.UV[platform].url
        source = tmp_path / 'digest'
        source.mkdir()
        (source / 'infer.py').write_bytes(b'pass\n')
        lock = tmp_path / 'worker/requirements.lock'
        lock.parent.mkdir()
        lock.write_text('pinned\n')
        monkeypatch.setattr(rs, 'worker_file', lambda path: tmp_path / 'worker' / path)
        monkeypatch.setitem(rs.SOURCE_TREE_DIGESTS, 'https://github.com/engine.zip', rs.tree_digest(source))
        rs.version_of.cache_clear()
        self.runtime = rs.Runtime(
            'rvc', 'RVC', '3.12', (('requirements.lock', 'https://index'), ('requirements.lock', '')),
            'https://github.com/engine.zip', rs.source_digest(source), '',
            (rs.Asset('https://huggingface.co/model.bin', 'base/model.bin', len(self.asset),
                      hashlib.sha256(self.asset).hexdigest()),),
            'MIT', ('https://license',), 'rvc', 10, 0)
        self.commands, self.requests = [], []
        self.fail_on = None
        self.hang_on = None
        self.child = None
        self.setup = rs.RuntimeSetup(tmp_path / 'runtimes', transport=self.open, launcher=self.launch,
                                     entries=(self.runtime,), gpu_check=lambda: True)

    def open(self, url, *, hosts):
        self.requests.append(url)
        assert hosts == rs.SOURCE_HOSTS
        if url == self.uv_url:
            return Response(self.tool)
        return Response(source_zip(self.source) if url.endswith('engine.zip') else self.asset)

    def launch(self, args, *, stdin, stdout, stderr, env, cwd):
        self.commands.append(args)
        self.env = env
        if self.hang_on and self.hang_on in args:
            self.child = Child(wait_forever=True)
            return self.child
        if 'venv' in args:
            python = Path(args[-1]).parent / PYTHON[self.platform]
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text('')
        return Child(1 if self.fail_on and self.fail_on in args else 0)

    def start(self):
        return self.setup.start(dict(id='rvc', consent=True, version=rs.version_of(self.runtime)))

    def finish(self, phases=('ready', 'failed', 'cancelled')):
        deadline = time.monotonic() + 5
        while self.setup.state()['jobs']['rvc']['phase'] not in phases:
            assert time.monotonic() < deadline, self.setup.state()
            time.sleep(.005)
        self.setup.thread.join(5)
        return self.setup.state()


@pytest.fixture(params=['win32', 'linux'])
def world(request, tmp_path, monkeypatch):
    item = World(tmp_path, monkeypatch, request.param)
    yield item
    assert item.setup.close(2)
    rs.version_of.cache_clear()


def test_nothing_starts_without_consent_for_this_exact_version(world):
    version = rs.version_of(world.runtime)
    for request, code in ((dict(id='rvc', consent=False, version=version), 'consent_required'),
                          (dict(id='rvc', consent=True, version='old'), 'vc_runtime_changed'),
                          (dict(id='other', consent=True, version=version), 'vc_runtime_changed'),
                          (dict(id='rvc', consent=True), 'vc_runtime_request_invalid')):
        with pytest.raises(ValueError, match=code):
            world.setup.start(request)
    assert world.commands == [] and world.requests == []


def test_a_full_setup_leaves_the_layout_the_worker_expects(world):
    world.start()
    state = world.finish()
    job = state['jobs']['rvc']
    folder = world.setup.folder(world.runtime)
    assert job['phase'] == 'ready' and job['path'] == str(folder)
    assert state['installed'] == {'rvc': str(folder)}
    assert (folder / 'engine/infer.py').read_bytes() == b'pass\n'
    assert (folder / 'assets/base/model.bin').read_bytes() == world.asset
    assert (folder / PYTHON[world.platform]).is_file()
    assert not (folder / 'engine.zip').exists() and not (folder / '.cache').exists()


def test_uv_is_unpacked_from_the_release_file_of_the_platform(world):
    world.start()
    world.finish()
    tools = world.setup.root / f'.uv-{rs.UV_VERSION}'
    uv = tools / ('uv.exe' if world.platform == 'win32' else 'uv')
    assert uv.read_bytes() == b'uv' and [path.name for path in tools.iterdir()] == [uv.name]
    assert world.commands[0][0] == str(uv)
    if world.platform == 'linux' and os.name == 'posix':
        assert uv.stat().st_mode & 0o777 == 0o700


def test_uv_runs_isolated_and_only_from_the_hash_locks(world):
    world.start()
    world.finish()
    venv, first, second, check = world.commands
    assert venv[1:5] == ['venv', '--no-config', '--managed-python', '--clear']
    assert '--require-hashes' in first and first[first.index('--index-url') + 1] == 'https://index'
    assert '--require-hashes' in second and '--index-url' not in second
    assert check[1:] == ['-c', rs.CUDA_CHECK]
    folder = world.setup.folder(world.runtime)
    assert world.env['UV_CACHE_DIR'] == str(folder / '.cache')
    assert world.env['UV_PYTHON_INSTALL_DIR'] == str(folder / 'python')


def test_a_failed_setup_names_its_step_and_resumes_after_what_finished(world):
    world.fail_on = 'pip'
    world.start()
    job = world.finish()['jobs']['rvc']
    assert (job['phase'], job['error_code']) == ('failed', 'vc_runtime_packages_failed')
    assert world.setup.state()['installed'] == {}
    world.fail_on = None
    world.commands.clear(), world.requests.clear()
    world.start()
    assert world.finish()['jobs']['rvc']['phase'] == 'ready'
    assert world.uv_url not in world.requests and not any('venv' in command for command in world.commands)


def test_a_source_that_differs_from_the_pin_is_never_used(world):
    world.source = {'infer.py': 'pass\n', 'injected.py': 'pass\n'}
    world.start()
    job = world.finish()['jobs']['rvc']
    assert job['error_code'] == 'vc_runtime_source_failed'
    assert not (world.setup.folder(world.runtime) / 'engine').exists()


@pytest.mark.parametrize('extra', [{'configs/v2.json': '{"injected": true}'}, {'lib/native.dll': 'MZ'},
                                   {'infer.pyc': 'compiled'}])
def test_a_changed_or_added_file_that_is_not_python_is_refused(world, extra):
    """SEC-04: the .py digest alone accepted these; the digest of every file does not."""
    world.source = {'infer.py': 'pass\n', **extra}
    world.start()
    job = world.finish()['jobs']['rvc']
    assert job['error_code'] == 'vc_runtime_source_failed'
    folder = world.setup.folder(world.runtime)
    assert not (folder / 'engine').exists() and not (folder / 'engine.part').exists()
    assert not (folder / 'engine.zip').exists()


def test_a_source_with_no_pinned_files_is_not_fetched(world, monkeypatch):
    monkeypatch.delitem(rs.SOURCE_TREE_DIGESTS, 'https://github.com/engine.zip')
    world.start()
    assert world.finish()['jobs']['rvc']['error_code'] == 'vc_runtime_source_failed'
    assert 'https://github.com/engine.zip' not in world.requests


def test_both_engines_have_their_files_pinned():
    for runtime in (rs.rvc_runtime(), rs.seed_runtime()):
        assert re.fullmatch(r'[0-9a-f]{64}', rs.SOURCE_TREE_DIGESTS[runtime.source_url]), runtime.id


def test_a_corrupt_asset_is_rejected_and_not_kept(world):
    world.asset = b'WEIGHTS'
    world.start()
    job = world.finish()['jobs']['rvc']
    assert job['error_code'] == 'vc_runtime_assets_failed'
    folder = world.setup.folder(world.runtime)
    assert not list((folder / 'assets').rglob('*.bin*'))


def test_a_pc_without_cuda_is_told_so_after_the_check(world):
    world.fail_on = rs.CUDA_CHECK
    world.start()
    assert world.finish()['jobs']['rvc']['error_code'] == 'vc_runtime_gpu_unusable'


def test_cancel_kills_the_installer_and_a_new_start_continues(world):
    world.hang_on = 'pip'
    state = world.start()
    job = state['jobs']['rvc']
    deadline = time.monotonic() + 5
    while world.child is None:
        assert time.monotonic() < deadline
        time.sleep(.005)
    world.setup.cancel('rvc', job['job_id'])
    assert world.finish()['jobs']['rvc']['phase'] == 'cancelled'
    assert world.child.killed
    world.hang_on = None
    world.start()
    assert world.finish()['jobs']['rvc']['phase'] == 'ready'


def test_only_one_setup_runs_and_closing_stops_it(world):
    world.hang_on = 'pip'
    world.start()
    with pytest.raises(ValueError, match='vc_runtime_busy'):
        world.start()
    assert world.setup.close(3)
    assert world.setup.state()['jobs']['rvc']['phase'] == 'cancelled'
    with pytest.raises(ValueError, match='vc_runtime_closed'):
        world.start()


def test_a_new_lock_makes_a_finished_runtime_stale(world, tmp_path):
    world.start()
    world.finish()
    (tmp_path / 'worker/requirements.lock').write_text('newer\n')
    rs.version_of.cache_clear()
    assert world.setup.state()['installed'] == {}


@pytest.mark.parametrize('damage', ['python', 'engine', 'assets'])
def test_a_damaged_runtime_can_be_set_up_again(world, damage):
    world.start()
    world.finish()
    folder = world.setup.folder(world.runtime)
    path = folder / (PYTHON[world.platform] if damage == 'python' else damage)
    shutil.rmtree(path) if path.is_dir() else path.unlink()
    assert world.setup.state()['installed'] == {}
    world.start()
    assert world.finish()['installed'] == {'rvc': str(folder)}
    assert (folder / PYTHON[world.platform]).is_file()
    assert (folder / 'engine/infer.py').is_file() and (folder / 'assets/base/model.bin').is_file()


def test_the_driver_check_only_looks_for_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, 'target', lambda: 'win32')
    monkeypatch.setenv('SystemRoot', str(tmp_path))
    assert rs.nvidia_driver() is False
    (tmp_path / 'System32').mkdir()
    (tmp_path / 'System32/nvcuda.dll').write_bytes(b'')
    assert rs.nvidia_driver() is True


def test_the_linux_driver_check_looks_for_what_the_kernel_driver_publishes(tmp_path, monkeypatch):
    assert rs.LINUX_DRIVER == Path('/proc/driver/nvidia/version')
    monkeypatch.setattr(rs, 'target', lambda: 'linux')
    monkeypatch.setattr(rs, 'LINUX_DRIVER', tmp_path / 'version')
    assert rs.nvidia_driver() is False
    (tmp_path / 'version').write_text('NVRM version: NVIDIA UNIX Open Kernel Module for x86_64\n')
    assert rs.nvidia_driver() is True


def test_the_catalog_says_what_will_be_fetched_and_where(world):
    row = world.setup.catalog()['runtimes'][0]
    assert row['destination'] == str(world.setup.folder(world.runtime))
    assert row['version'] == rs.version_of(world.runtime) and row['gpu_ready'] is True
    assert row['license'] == 'MIT' and row['licenses'] == ['https://license']


@pytest.mark.parametrize('system, machine, expected', [
    ('win32', 'AMD64', 'win32'), ('linux', 'x86_64', 'linux'), ('linux', 'aarch64', ''), ('darwin', 'x86_64', '')])
def test_setup_is_offered_where_the_locked_wheels_fit(monkeypatch, system, machine, expected):
    monkeypatch.setattr(rs.sys, 'platform', system)
    monkeypatch.setattr(rs.platform, 'machine', lambda: machine)
    assert rs.target() == expected
    if not expected:
        assert rs.runtimes() == ()


LOCKS = {'win32': {'rvc': ['integrations/rvc/requirements-cuda-windows.lock', 'integrations/rvc/requirements-windows.lock'],
                   'seed-vc': ['integrations/seed_vc/requirements-windows.lock']},
         'linux': {'rvc': ['integrations/rvc/requirements-cuda.lock', 'integrations/rvc/requirements.lock'],
                   'seed-vc': ['integrations/seed_vc/requirements.lock']}}


@pytest.fixture(params=['win32', 'linux'])
def platform(request, monkeypatch):
    monkeypatch.setattr(rs, 'target', lambda: request.param)
    rs.version_of.cache_clear()
    yield request.param
    rs.version_of.cache_clear()


def test_each_platform_installs_from_its_own_hash_locked_files(platform):
    offered = {runtime.id: runtime for runtime in rs.runtimes()}
    assert {key: [path for path, _ in runtime.locks] for key, runtime in offered.items()} == LOCKS[platform]
    assert [index for _, index in offered['rvc'].locks] == [rs.CUDA_INDEX, '']
    for runtime in offered.values():
        assert runtime.download_bytes > 2_000_000_000 and runtime.disk_bytes > runtime.download_bytes
        for path, _ in runtime.locks:
            # Every requirement names its hashes, or uv refuses the whole file.
            entries = re.split(r'\n(?=[A-Za-z0-9])', (ROOT / path).read_text(encoding='utf-8'))
            entries = [entry for entry in entries if not entry.startswith('#')]
            assert len(entries) > 5 and all('--hash=sha256:' in entry or '#sha256=' in entry for entry in entries)


def test_the_pinned_uv_is_the_release_file_of_each_platform(platform):
    tool = rs.UV[platform]
    name = {'win32': 'uv-x86_64-pc-windows-msvc.zip', 'linux': 'uv-x86_64-unknown-linux-gnu.tar.gz'}[platform]
    assert tool.url == f'https://github.com/astral-sh/uv/releases/download/{rs.UV_VERSION}/{name}'
    assert tool.size > 10_000_000 and re.fullmatch('[0-9a-f]{64}', tool.sha256)
    assert transport.validate_url(tool.url, rs.SOURCE_HOSTS)


def test_one_platforms_pins_do_not_change_what_the_other_consented_to(platform, monkeypatch):
    other = 'linux' if platform == 'win32' else 'win32'
    before = {runtime.id: rs.version_of(runtime) for runtime in rs.runtimes()}
    monkeypatch.setitem(rs.UV, other, replace(rs.UV[other], sha256='0' * 64))
    monkeypatch.setitem(rs.RVC_PLATFORM, other, (rs.RVC_PLATFORM[other][0], 1, 2))
    rs.version_of.cache_clear()
    assert {runtime.id: rs.version_of(runtime) for runtime in rs.runtimes()} == before
    monkeypatch.setitem(rs.UV, platform, replace(rs.UV[platform], sha256='0' * 64))
    rs.version_of.cache_clear()
    assert all(rs.version_of(runtime) != before[runtime.id] for runtime in rs.runtimes())


def test_setup_and_start_agree_on_the_python_of_this_platform(tmp_path):
    from models.voice_conversion import rvc_process
    assert rs.runtime_python(tmp_path) == rvc_process.runtime_python(tmp_path)


def test_unpacking_refuses_to_leave_the_target(tmp_path):
    archive = tmp_path / 'source.zip'
    with zipfile.ZipFile(archive, 'w') as source:
        source.writestr('top/../../evil.py', 'x')
    with pytest.raises(ValueError, match='source_path_unsafe'):
        rs.unpack_source(archive, tmp_path / 'out')


def _archive(tmp_path, entries):
    archive = tmp_path / 'source.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as source:
        for entry in entries:
            if isinstance(entry, zipfile.ZipInfo):
                source.writestr(entry, b'target')
            else:
                name, data = entry
                source.writestr(name, data)
    return archive


def _symlink(name):
    info = zipfile.ZipInfo(name)
    info.external_attr = (0o120777 << 16)
    return info


@pytest.mark.parametrize('entries,code', [
    ([('/top/a.py', 'x')], 'source_path_unsafe'),
    ([('top/C:/a.py', 'x')], 'source_path_unsafe'),
    ([('top\\..\\a.py', 'x')], 'source_path_unsafe'),
    ([('top/a\x01.py', 'x')], 'source_path_unsafe'),
    ([('top/a.py', 'x'), ('other/b.py', 'x')], 'source_path_unsafe'),
    ([('top/Engine.py', 'x'), ('top/engine.py', 'y')], 'source_path_unsafe'),
    ([('top/a.py', 'x'), _symlink('top/link')], 'source_entry_type'),
])
def test_unpacking_refuses_unsafe_entries_before_writing_anything(tmp_path, entries, code):
    """SEC-04: every entry is checked first, so a refused archive leaves nothing behind."""
    archive = _archive(tmp_path, entries)
    with pytest.raises(ValueError, match=code):
        rs.unpack_source(archive, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_unpacking_refuses_encrypted_entries(tmp_path):
    archive = _archive(tmp_path, [('top/a.py', 'x')])
    data = bytearray(archive.read_bytes())
    # The general purpose flag of the local header and of the central directory entry.
    for signature, offset in ((b'PK\x03\x04', 6), (b'PK\x01\x02', 8)):
        at = data.index(signature) + offset
        data[at] |= 0x1
    archive.write_bytes(bytes(data))
    with pytest.raises(ValueError, match='source_entry_type'):
        rs.unpack_source(archive, tmp_path / 'out')


@pytest.mark.parametrize('limit,value', [('SOURCE_MAX_ENTRIES', 3), ('SOURCE_MAX_BYTES', 100), ('SOURCE_MAX_RATIO', 10)])
def test_unpacking_refuses_archives_over_the_limits(tmp_path, monkeypatch, limit, value):
    archive = _archive(tmp_path, [(f'top/{index}.txt', b'\0' * 1000) for index in range(4)])
    monkeypatch.setattr(rs, limit, value)
    with pytest.raises(ValueError, match='source_too_large'):
        rs.unpack_source(archive, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_an_archive_within_the_limits_unpacks_without_its_top_folder(tmp_path):
    archive = _archive(tmp_path, [('top/', b''), ('top/sub/', b''), ('top/sub/a.py', 'pass\n'), ('top/data.bin', b'\x00\x01')])
    rs.unpack_source(archive, tmp_path / 'out')
    assert (tmp_path / 'out/sub/a.py').read_bytes() == b'pass\n'
    assert (tmp_path / 'out/data.bin').read_bytes() == b'\x00\x01'


def test_the_tree_digest_covers_every_file_and_its_name(tmp_path):
    (tmp_path / 'a.py').write_text('pass\n')
    first = rs.tree_digest(tmp_path)
    assert first == rs.source_digest(tmp_path)  # With only .py files the two agree.
    (tmp_path / 'b.json').write_text('{}')
    second = rs.tree_digest(tmp_path)
    assert second != first and rs.source_digest(tmp_path) == first
    (tmp_path / 'b.json').rename(tmp_path / 'c.json')
    assert rs.tree_digest(tmp_path) not in (first, second)


PATCH = '''--- a/engine.py
+++ b/engine.py
@@ -1,4 +1,4 @@
 first
-second
+changed
 third
 fourth
@@ -6,3 +6,5 @@
 sixth
+added
+more
 seventh
 eighth
'''
SOURCE = 'first\nsecond\nthird\nfourth\nfifth\nsixth\nseventh\neighth\n'


def test_a_patch_edits_and_keeps_later_hunks_aligned(tmp_path):
    (tmp_path / 'engine.py').write_bytes(SOURCE.encode())
    rs.apply_patch(tmp_path, PATCH)
    assert (tmp_path / 'engine.py').read_bytes() == (
        b'first\nchanged\nthird\nfourth\nfifth\nsixth\nadded\nmore\nseventh\neighth\n')


def test_a_patch_keeps_the_files_line_endings(tmp_path):
    (tmp_path / 'engine.py').write_bytes(SOURCE.replace('\n', '\r\n').encode())
    rs.apply_patch(tmp_path, PATCH)
    assert b'changed\r\nthird\r\n' in (tmp_path / 'engine.py').read_bytes()


def test_a_patch_refuses_context_that_differs(tmp_path):
    (tmp_path / 'engine.py').write_bytes(SOURCE.replace('third', 'THIRD').encode())
    with pytest.raises(ValueError, match='patch_mismatch'):
        rs.apply_patch(tmp_path, PATCH)


def test_seed_assets_follow_the_reviewed_manifest():
    manifest = json.loads((ROOT / rs.SEED_MANIFEST).read_text(encoding='utf-8'))
    assets = rs.seed_assets(manifest)
    assert sum(asset.size for asset in assets) == manifest['total_bytes']
    assert all(asset.sha256 or asset.blob for asset in assets)
    item = next(row for row in manifest['files'] if row['rfilename'] == 'model.pt')
    asset = next(row for row in assets if row.path.endswith('/model.pt'))
    assert asset.path == f"{item['repo']}/{item['revision']}/model.pt"
    assert asset.url.startswith(f"https://huggingface.co/{item['repo']}/resolve/{item['revision']}/")


def test_the_routes_are_registered():
    text = (ROOT / 'src-python/mainloop.py').read_text(encoding='utf-8')
    for route in ('/get/data/vc_runtime_catalog', '/get/data/vc_runtime_state',
                  '/run/start_vc_runtime_setup', '/run/cancel_vc_runtime_setup'):
        assert f'"{route}"' in text


def test_the_digest_matches_the_one_the_worker_checks(tmp_path):
    loader = importlib.import_module('integrations.rvc.loader')
    (tmp_path / 'infer').mkdir()
    (tmp_path / 'infer/module.py').write_text('pass\n')
    assert rs.source_digest(tmp_path) == loader.source_digest(tmp_path)
    assert rs.RVC_COMMIT == loader.COMMIT


def test_pinned_files_match_the_reviewed_records(platform):
    loader = importlib.import_module('integrations.rvc.loader')
    rvc = rs.rvc_runtime()
    assert rvc.source_digest == loader.SOURCE_DIGEST
    record = json.loads((ROOT / 'docs/voice-stack/rvc-base-artifacts.proposal.json').read_text(encoding='utf-8'))
    pinned = {asset.url.rsplit('/', 1)[-1]: asset for asset in rvc.assets}
    for item in record['files']:
        assert item['revision'] == rs.RVC_REVISION
        asset = pinned[item['rfilename'].rsplit('/', 1)[-1]]
        assert asset.size == item['size']
        if 'lfs' in item:
            assert asset.sha256 == item['lfs']['sha256']


def test_requests_for_other_hosts_stay_refused():
    with pytest.raises(ValueError, match='download_url_rejected'):
        transport.validate_url('https://github.com/engine.zip')
    assert transport.validate_url('https://github.com/engine.zip', rs.SOURCE_HOSTS)
    with pytest.raises(ValueError, match='download_url_rejected'):
        transport.validate_url('https://example.com/engine.zip', rs.SOURCE_HOSTS)


def test_the_linux_bundle_carries_what_the_setup_installs_from(tmp_path, monkeypatch):
    from tools.build_linux import copy_adapters
    copy_adapters(tmp_path)
    monkeypatch.setattr(rs, 'target', lambda: 'linux')
    monkeypatch.setattr(rs, 'worker_file', lambda path: tmp_path / path)
    rs.version_of.cache_clear()
    try:
        for runtime in rs.runtimes():
            assert rs.version_of(runtime)
            assert all((tmp_path / path).is_file() for path, _ in runtime.locks)
            assert not runtime.patch or (tmp_path / runtime.patch).is_file()
    finally:
        rs.version_of.cache_clear()
    names = {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob('*.lock')}
    assert not any('windows' in name for name in names)
    from tools.linux_package import RUNTIME
    assert {'_internal/' + name for name in names} <= set(RUNTIME)
    assert '_internal/integrations/seed_vc/offline-loader.patch' in RUNTIME


linux_only = pytest.mark.skipif(sys.platform != 'linux', reason='the Linux launcher')


def running(pid):
    """False once the process is gone or only waits to be reaped."""
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except OSError:
        return False


@linux_only
def test_cancelling_on_linux_also_stops_what_uv_started(tmp_path):
    script = 'sleep 60 & echo $! > child; wait'
    child = rs.launch_group(['/bin/sh', '-c', script], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env=dict(os.environ), cwd=str(tmp_path))
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / 'child').is_file() or not (tmp_path / 'child').read_text().strip():
            assert time.monotonic() < deadline
            time.sleep(.01)
        grandchild = int((tmp_path / 'child').read_text())
        assert os.getpgid(child.pid) == child.pid == os.getpgid(grandchild)
        child.kill()
        assert child.wait(5) == -signal.SIGKILL
        deadline = time.monotonic() + 5
        while running(grandchild):
            assert time.monotonic() < deadline, 'what the child started outlived it'
            time.sleep(.01)
        child.kill()  # A finished child is left alone.
    finally:
        child.kill()


@linux_only
def test_a_linux_setup_child_does_not_outlive_the_app(tmp_path):
    """The app here is a separate Python that starts the child from a thread and is then killed."""
    program = textwrap.dedent('''
        import subprocess, sys, threading, time
        from models.voice_conversion import runtime_setup as rs

        def work():
            child = rs.launch_group(['/bin/sleep', '60'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=None, cwd=None)
            print(child.pid, flush=True)
            child.wait()

        threading.Thread(target=work).start()
        time.sleep(60)
    ''')
    app = subprocess.Popen([sys.executable, '-c', program], stdout=subprocess.PIPE, text=True,
                           env=dict(os.environ, PYTHONPATH=str(ROOT / 'src-python')))
    try:
        pid = int(app.stdout.readline())
        assert running(pid)
        app.kill()
        app.wait(5)
        deadline = time.monotonic() + 5
        while running(pid):
            assert time.monotonic() < deadline, 'the child outlived the app'
            time.sleep(.01)
    finally:
        app.kill()
        app.wait(5)
