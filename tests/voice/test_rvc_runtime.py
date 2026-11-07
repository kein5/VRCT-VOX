"""Pure local validation; no optional ML imports or model installation."""

import subprocess

import pytest


def test_source_pin_rejects_modified_and_untracked_python(tmp_path, monkeypatch):
    from integrations.rvc import loader

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(tmp_path), *args], text=True
        ).strip()

    git("init", "-q")
    source = tmp_path / "infer.py"
    source.write_text("pass\n")
    git("add", "infer.py")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@invalid",
        "commit",
        "-qm",
        "fixture",
    )
    monkeypatch.setattr(loader, "COMMIT", git("rev-parse", "HEAD"))
    loader.require_source(tmp_path)
    source.write_text("modified\n")
    with pytest.raises(ValueError, match="vc_source_unverified"):
        loader.require_source(tmp_path)
    source.write_text("pass\n")
    (tmp_path / "injected.py").write_text("pass\n")
    with pytest.raises(ValueError, match="vc_source_unverified"):
        loader.require_source(tmp_path)


def test_a_tree_with_the_pinned_digest_needs_no_git(tmp_path, monkeypatch):
    from integrations.rvc import loader

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    (tmp_path / "infer").mkdir()
    (tmp_path / "infer/module.py").write_text("pass\n")
    monkeypatch.setattr(loader, "SOURCE_DIGEST", loader.source_digest(tmp_path))
    monkeypatch.setattr(loader.subprocess, "check_output", no_git)
    loader.require_source(tmp_path)
    (tmp_path / "injected.py").write_text("pass\n")
    with pytest.raises(ValueError, match="vc_source_unverified"):
        loader.require_source(tmp_path)


def test_source_digest_covers_names_and_contents(tmp_path):
    from integrations.rvc import loader

    (tmp_path / "a.py").write_text("pass\n")
    first = loader.source_digest(tmp_path)
    (tmp_path / "a.py").write_text("pass  \n")
    changed = loader.source_digest(tmp_path)
    (tmp_path / "a.py").rename(tmp_path / "b.py")
    assert len({first, changed, loader.source_digest(tmp_path)}) == 3


def test_missing_local_assets_fail_without_loading_torch(tmp_path):
    from integrations.rvc.loader import require_assets

    with pytest.raises(ValueError, match="vc_assets_missing"):
        require_assets(tmp_path)
