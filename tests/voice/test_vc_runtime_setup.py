"""The runtime setup with fake transfers and a fake uv: consent, resume, cancel, failure."""
import hashlib
import importlib
import io
import json
from pathlib import Path
import subprocess
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


def tool_zip():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('uv.exe', b'uv')
    return stream.getvalue()


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
    def __init__(self, tmp_path, monkeypatch):
        self.source = {'infer.py': 'pass\n'}
        self.asset = b'weights'
        self.tool = tool_zip()
        monkeypatch.setattr(rs, 'UV_SIZE', len(self.tool))
        monkeypatch.setattr(rs, 'UV_SHA256', hashlib.sha256(self.tool).hexdigest())
        source = tmp_path / 'digest'
        source.mkdir()
        (source / 'infer.py').write_bytes(b'pass\n')
        lock = tmp_path / 'worker/requirements.lock'
        lock.parent.mkdir()
        lock.write_text('pinned\n')
        monkeypatch.setattr(rs, 'worker_file', lambda path: tmp_path / 'worker' / path)
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
        assert 'github.com' in hosts
        if url == rs.UV_URL:
            return Response(self.tool)
        return Response(source_zip(self.source) if url.endswith('engine.zip') else self.asset)

    def launch(self, args, *, stdin, stdout, stderr, env, cwd):
        self.commands.append(args)
        self.env = env
        if self.hang_on and self.hang_on in args:
            self.child = Child(wait_forever=True)
            return self.child
        if 'venv' in args:
            python = Path(args[-1]) / 'Scripts/python.exe'
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


@pytest.fixture
def world(tmp_path, monkeypatch):
    item = World(tmp_path, monkeypatch)
    yield item
    assert item.setup.close(2)


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
    assert (folder / 'venv/Scripts/python.exe').is_file()
    assert not (folder / 'engine.zip').exists() and not (folder / '.cache').exists()


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
    assert rs.UV_URL not in world.requests and not any('venv' in command for command in world.commands)


def test_a_source_that_differs_from_the_pin_is_never_used(world):
    world.source = {'infer.py': 'pass\n', 'injected.py': 'pass\n'}
    world.start()
    job = world.finish()['jobs']['rvc']
    assert job['error_code'] == 'vc_runtime_source_failed'
    assert not (world.setup.folder(world.runtime) / 'engine').exists()


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


def test_the_catalog_says_what_will_be_fetched_and_where(world):
    row = world.setup.catalog()['runtimes'][0]
    assert row['destination'] == str(world.setup.folder(world.runtime))
    assert row['version'] == rs.version_of(world.runtime) and row['gpu_ready'] is True
    assert row['license'] == 'MIT' and row['licenses'] == ['https://license']


def test_other_platforms_offer_no_setup(monkeypatch):
    monkeypatch.setattr(rs.sys, 'platform', 'linux')
    assert rs.runtimes() == ()


def test_unpacking_refuses_to_leave_the_target(tmp_path):
    archive = tmp_path / 'source.zip'
    with zipfile.ZipFile(archive, 'w') as source:
        source.writestr('top/../../evil.py', 'x')
    with pytest.raises(ValueError, match='source_path_unsafe'):
        rs.unpack_source(archive, tmp_path / 'out')


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
    assert rs.RVC.source_digest == loader.SOURCE_DIGEST
    assert rs.RVC_COMMIT == loader.COMMIT


def test_pinned_files_match_the_reviewed_records():
    record = json.loads((ROOT / 'docs/voice-stack/rvc-base-artifacts.proposal.json').read_text(encoding='utf-8'))
    pinned = {asset.url.rsplit('/', 1)[-1]: asset for asset in rs.RVC.assets}
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
