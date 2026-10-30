"""Linux distribution policy: preserve valid links, fail on unsafe payloads."""
import io
import tarfile

import pytest

from tools.linux_package import check_tree, inspect_tar, pack, normalize_modes


@pytest.mark.parametrize('engine', ['rvc', 'seed_vc'])
def test_packaged_vc_worker_can_start_outside_source_checkout(tmp_path, engine):
    import subprocess
    import sys
    from tools.build_linux import copy_adapters
    resources = tmp_path/'relocated-internal'
    resources.mkdir()
    copy_adapters(resources)
    # A real external interpreter cannot import modules hidden in the sidecar PYZ.
    # --help exercises imports before model loading; no ML packages/downloads needed.
    result = subprocess.run([sys.executable, '-E', '-s', '-m',
        f'integrations.{engine}.live_worker', '--help'], cwd=resources,
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert '--session' in result.stdout


def test_internal_file_link_survives_archive(tmp_path):
    root = tmp_path / 'VRCT-VOX'
    (root / 'lib').mkdir(parents=True)
    (root / 'lib/library.so.1').write_bytes(b'library')
    (root / 'lib/library.so').symlink_to('library.so.1')
    archive = tmp_path / 'candidate.tar.gz'
    pack(root, archive, require_runtime=False)
    assert (tmp_path / 'candidate.tar.gz.sha256').is_file()
    assert inspect_tar(archive) == 4
    with tarfile.open(archive) as src:
        assert src.getmember('VRCT-VOX/lib/library.so').issym()


@pytest.mark.parametrize('target', ['missing', 'cycle', '../outside', '/etc/hosts', 'directory'])
def test_tree_rejects_bad_links(tmp_path, target):
    root = tmp_path / 'candidate'
    root.mkdir()
    (root / 'directory').mkdir()
    (tmp_path / 'outside').write_text('outside')
    (root / 'cycle').symlink_to(target)
    with pytest.raises(ValueError):
        check_tree(root)


@pytest.mark.parametrize('name', ['ocr_onnx/chatbox_yolo.onnx', 'Mia2026.pth', 'rapidocr/model.onnx'])
def test_forbidden_assets_blocked(tmp_path, name):
    file = tmp_path / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b'model')
    with pytest.raises(ValueError):
        check_tree(tmp_path)


def test_pack_requires_complete_runtime(tmp_path):
    root = tmp_path / 'VRCT-VOX'
    root.mkdir()
    (root / 'vrct-vox').write_text('#!/bin/sh\n')
    with pytest.raises(ValueError, match='runtime'):
        pack(root, tmp_path / 'out.tar.gz')
    assert not (tmp_path / 'out.tar.gz').exists()


def tar_with(tmp_path, entries):
    path = tmp_path / 'input.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        for name, kind, target in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.linkname = target
            archive.addfile(member, io.BytesIO())
    return path


@pytest.mark.parametrize('entries', [
    [('../escape', tarfile.REGTYPE, '')],
    [('/absolute', tarfile.REGTYPE, '')],
    [('pkg/ok', tarfile.REGTYPE, ''), ('pkg/ok', tarfile.REGTYPE, '')],
    [('pkg/link', tarfile.SYMTYPE, '../../etc/passwd')],
    [('pkg/link', tarfile.SYMTYPE, 'link')],
    [('pkg/link', tarfile.SYMTYPE, 'missing')],
    [('pkg/hard', tarfile.LNKTYPE, 'pkg/file')],
    [('pkg/fifo', tarfile.FIFOTYPE, '')],
    [('pkg/ocr/x.onnx', tarfile.REGTYPE, '')],
    [('pkg/secret.zip', tarfile.REGTYPE, '')],
    [('pkg/a', tarfile.REGTYPE, ''), ('elsewhere/b', tarfile.REGTYPE, '')],
    [('pkg/a', tarfile.SYMTYPE, 'file'), ('pkg/a/b', tarfile.REGTYPE, ''), ('pkg/file', tarfile.REGTYPE, '')],
])
def test_tar_rejects_unsafe_or_uninspectable_entries(tmp_path, entries):
    with pytest.raises(ValueError):
        inspect_tar(tar_with(tmp_path, entries))


def test_default_distribution_guard_still_rejects_links(tmp_path):
    from tools.check_voice_distribution import check
    (tmp_path / 'real').write_text('safe')
    (tmp_path / 'link').symlink_to('real')
    with pytest.raises(ValueError):
        check([tmp_path])


def test_packaged_modes_are_readable_by_installing_user(tmp_path):
    (tmp_path / 'dir').mkdir(mode=0o700)
    data = tmp_path / 'dir/data'
    data.write_text('data')
    data.chmod(0o600)
    binary = tmp_path / 'program'
    binary.write_bytes(b'executable')
    binary.chmod(0o700)
    (tmp_path / 'link').symlink_to('program')
    normalize_modes(tmp_path)
    assert tmp_path.stat().st_mode & 0o777 == 0o755
    assert (tmp_path / 'dir').stat().st_mode & 0o777 == 0o755
    assert data.stat().st_mode & 0o777 == 0o644
    assert binary.stat().st_mode & 0o777 == 0o755
    assert (tmp_path / 'link').is_symlink()


def test_build_refuses_existing_unowned_work_area(tmp_path):
    from tools.build_linux import prepare_work
    (tmp_path / 'resources').mkdir()
    (tmp_path / 'resources/user-file').write_text('keep')
    with pytest.raises(ValueError, match='dedicated'):
        prepare_work(tmp_path)
    assert (tmp_path / 'resources/user-file').read_text() == 'keep'


def test_build_reuses_only_marked_work_area(tmp_path):
    from tools.build_linux import prepare_work
    work = tmp_path / 'build'
    assert prepare_work(work) == work
    (work / 'resources').mkdir()
    assert prepare_work(work) == work
    link = tmp_path / 'link'
    link.symlink_to(work, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare_work(link)


def test_tar_checks_renamed_nested_zip(tmp_path):
    import zipfile
    root = tmp_path / 'VRCT-VOX'
    root.mkdir()
    with zipfile.ZipFile(root / 'data.dat', 'w') as archive:
        archive.writestr('ocr/model.onnx', b'model')
    with pytest.raises(ValueError):
        pack(root, tmp_path / 'out.tar.gz', require_runtime=False)
