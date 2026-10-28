"""Pure local validation; no optional ML imports or model installation."""
from pathlib import Path
import subprocess

import pytest


def test_source_pin_rejects_modified_and_untracked_python(tmp_path, monkeypatch):
    from integrations.rvc import loader
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()
    git('init', '-q')
    source = tmp_path / 'infer.py'
    source.write_text('pass\n')
    git('add', 'infer.py')
    git('-c', 'user.name=Test', '-c', 'user.email=test@invalid', 'commit', '-qm', 'fixture')
    monkeypatch.setattr(loader, 'COMMIT', git('rev-parse', 'HEAD'))
    loader.require_source(tmp_path)
    source.write_text('modified\n')
    with pytest.raises(ValueError, match='vc_source_unverified'):
        loader.require_source(tmp_path)
    source.write_text('pass\n')
    (tmp_path / 'injected.py').write_text('pass\n')
    with pytest.raises(ValueError, match='vc_source_unverified'):
        loader.require_source(tmp_path)


def test_missing_local_assets_fail_without_loading_torch(tmp_path):
    from integrations.rvc.loader import require_assets
    with pytest.raises(ValueError, match='vc_assets_missing'):
        require_assets(tmp_path)
