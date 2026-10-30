"""Security boundaries exercised without starting Explorer or using the network."""
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import yaml

from test_controller_integration import controller_module  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("method,setting", [
    ("openFilepathLogs", "PATH_LOGS"),
    ("openFilepathConfigFile", "PATH_LOCAL"),
])
@pytest.mark.parametrize("path", [
    "C:/Users/test/VRCT logs",
    "C:/Users/test/日本語 & (logs)",
    "C:/Users/test/%TEMP% & calc",
])
def test_directory_path_is_one_literal_argument(controller_module, monkeypatch, method, setting, path):  # noqa: F811
    launch = Mock()
    monkeypatch.setattr(controller_module, "Popen", launch)
    setattr(controller_module.config, setting, path)
    assert getattr(controller_module.Controller, method)() == {"status": 200, "result": True}
    args, kwargs = launch.call_args
    assert args == (["explorer", path.replace("/", "\\")],)
    assert kwargs.get("shell", False) is False


def test_network_probe_uses_tls_and_preserves_certificate_verification(monkeypatch):
    import utils
    request = Mock(return_value=SimpleNamespace(status_code=200))
    monkeypatch.setattr(utils.requests, "get", request)
    assert utils.isConnectedNetwork()
    args, kwargs = request.call_args
    assert args[0].startswith("https://")
    assert kwargs.get("verify", True) is True
    assert kwargs["timeout"] == 3
    request.side_effect = requests.exceptions.SSLError("invalid certificate")
    assert not utils.isConnectedNetwork()
    assert request.call_count == 2  # no plaintext retry on TLS failure


@pytest.mark.parametrize("workflow", sorted((ROOT / ".github/workflows").glob("*.yml")), ids=lambda p: p.name)
def test_workflows_pin_external_code_and_keep_inputs_out_of_scripts(workflow):
    document = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    if workflow.name == "prepare-release.yml":
        assert set(document["on"]) == {"workflow_dispatch"}
        assert document["permissions"] == {"contents": "read", "actions": "read"}
        assert set(document["jobs"]) == {"draft"}
        draft = document["jobs"]["draft"]
        assert draft["permissions"] == {"contents": "write", "actions": "read"}
        assert "github.repository == 'kein5/VRCT-VOX'" in draft["if"]
        assert "github.ref == 'refs/heads/develop'" in draft["if"]
        commands = "\n".join(step.get("run", "") for step in draft["steps"])
        assert "tools.prepare_release" in commands
        assert "'--draft'" in commands
        assert "release', 'edit'" not in commands
    else:
        assert document["permissions"] == {"contents": "read"}
        assert all("permissions" not in job for job in document["jobs"].values())
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step and not step["uses"].startswith("./"):
                assert re.fullmatch(r"[\w-]+/[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
            assert "${{" not in step.get("run", ""), step.get("name", workflow.name)
