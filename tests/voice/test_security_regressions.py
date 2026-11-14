"""Security boundaries exercised without starting Explorer or using the network."""
from pathlib import Path
import http.client
import re
import ssl
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from email.message import Message

import pytest
import yaml

from test_controller_integration import controller_module  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
# Workflow file -> the one job that signs build provenance for the release candidates.
ATTESTING_JOBS = {"build-linux.yml": "candidate", "release.yml": "candidate"}


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


@pytest.fixture
def recording_probe(monkeypatch):
    """Use real urllib/TLS setup, replacing HTTP I/O before a socket is opened."""
    state = SimpleNamespace(status=200, location=None, error=None, requests=[])

    def request(connection, method, url, body=None, headers=None, **kwargs):
        state.requests.append({"host": connection.host, "method": method, "url": url,
                               "body": body, "timeout": connection.timeout,
                               "verify_mode": connection._context.verify_mode,
                               "check_hostname": connection._context.check_hostname})
        if state.error:
            raise state.error

    def response(connection):
        headers = Message()
        if state.location:
            headers["Location"] = state.location
        result = MagicMock(status=state.status, code=state.status, reason="recorded", headers=headers)
        result.info.return_value = headers
        result.__enter__.return_value = result
        return result

    monkeypatch.setattr(http.client.HTTPSConnection, "request", request)
    monkeypatch.setattr(http.client.HTTPSConnection, "getresponse", response)
    plaintext_request = Mock(side_effect=AssertionError("Probe must never downgrade to plain HTTP"))
    monkeypatch.setattr(http.client.HTTPConnection, "request", plaintext_request)
    yield state
    # The probe catches transport errors; check attempts as well as its result.
    plaintext_request.assert_not_called()


def test_network_probe_uses_tls_and_preserves_certificate_verification(recording_probe):
    import utils
    probe = recording_probe
    assert utils.isConnectedNetwork()
    assert probe.requests == [{"host": "huggingface.co", "method": "HEAD", "url": "/",
                               "body": None, "timeout": 3, "verify_mode": ssl.CERT_REQUIRED,
                               "check_hostname": True}]
    probe.error = ssl.SSLCertVerificationError("invalid certificate")
    assert not utils.isConnectedNetwork()
    assert len(probe.requests) == 2  # No retry or plaintext fallback on TLS failure.


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("location", [
    "https://unselected.example/", "https://cdn-lfs.huggingface.co/", "http://huggingface.co/",
])
def test_network_probe_never_follows_redirects(recording_probe, status, location):
    import utils
    probe = recording_probe
    probe.status, probe.location = status, location
    assert not utils.isConnectedNetwork()
    assert len(probe.requests) == 1
    assert probe.requests[0]["host"] == "huggingface.co"


@pytest.mark.parametrize("workflow", sorted((ROOT / ".github/workflows").glob("*.yml")), ids=lambda p: p.name)
def test_workflows_pin_external_code_and_keep_inputs_out_of_scripts(workflow):
    document = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    if workflow.name == "prepare-release.yml":
        assert set(document["on"]) == {"workflow_dispatch"}
        assert document["permissions"] == {"contents": "read", "actions": "read"}
        assert set(document["jobs"]) == {"draft"}
        draft = document["jobs"]["draft"]
        assert draft["permissions"] == {"contents": "write", "actions": "read", "attestations": "read"}
        assert "github.repository == 'kein5/VRCT-VOX'" in draft["if"]
        assert "github.ref == 'refs/heads/develop'" in draft["if"]
        commands = "\n".join(step.get("run", "") for step in draft["steps"])
        assert "tools.prepare_release" in commands
        assert "'--draft'" in commands
        assert "release', 'edit'" not in commands
    elif workflow.name == "pages.yml":
        # Deploying to GitHub Pages needs pages:write and id-token:write. Only the
        # deploy job gets them, only on develop in this repository, never for a PR.
        assert document["permissions"] == {"contents": "read"}
        assert set(document["jobs"]) == {"build", "deploy"}
        assert "permissions" not in document["jobs"]["build"]
        deploy = document["jobs"]["deploy"]
        assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
        assert "github.repository == 'kein5/VRCT-VOX'" in deploy["if"]
        assert "github.ref == 'refs/heads/develop'" in deploy["if"]
        assert "github.event_name != 'pull_request'" in deploy["if"]
        assert all("run" not in step for step in deploy["steps"])
    elif workflow.name in ATTESTING_JOBS:
        # The candidate job signs build provenance (second security audit SEC-04): only that job
        # gets id-token and attestations, and only a manual run uses them.
        assert document["permissions"] == {"contents": "read"}
        for name, job in document["jobs"].items():
            if name != ATTESTING_JOBS[workflow.name]:
                assert "permissions" not in job, name
                continue
            assert job["permissions"] == {"contents": "read", "id-token": "write", "attestations": "write"}
            attest = [step for step in job["steps"] if step.get("uses", "").startswith("actions/attest-build-provenance@")]
            assert len(attest) == 1
            assert attest[0]["if"] == "github.event_name == 'workflow_dispatch'"
            assert attest[0]["with"]["subject-path"].endswith("release-candidate/*")
    else:
        assert document["permissions"] == {"contents": "read"}
        assert all("permissions" not in job for job in document["jobs"].values())
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step and not step["uses"].startswith("./"):
                assert re.fullmatch(r"[\w-]+/[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
            assert "${{" not in step.get("run", ""), step.get("name", workflow.name)
