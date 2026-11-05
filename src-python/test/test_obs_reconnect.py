from pathlib import Path
import shutil
import subprocess

import pytest

from models.obs import obs_browser_source_server as obs_module


def test_open_obs_page_refreshes_port_without_notification(monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the generated OBS page")
    monkeypatch.setattr(obs_module.config, "WEBSOCKET_PORT", 2231)
    result = subprocess.run(
        [node, str(Path(__file__).with_name("obs_reconnect.mjs"))],
        input=obs_module._build_overlay_html("test-token"),
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
