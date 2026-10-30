"""Report completeness comes from raw diagnostics, independently of exit codes."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.summarize_semgrep import summarize


def manifest(tmp_path, documents, **extra):
    scans = []
    for index, document in enumerate(documents):
        path = tmp_path / f"scan-{index}.json"
        path.write_text(json.dumps(document))
        scans.append({"json": path.name, "ruleset": f"p/{index}", "exitCode": 0, "partial": False})
    path = tmp_path / "scans.json"
    path.write_text(json.dumps({"scans": scans, **extra}))
    return path


def document():
    return {"results": [], "errors": [], "paths": {"scanned": ["app.py"]}, "skipped_rules": []}


def test_exit_zero_with_diagnostics_does_not_claim_complete(tmp_path):
    raw = document()
    raw["errors"] = [{"type": "Timeout", "path": "app.py", "message": "timed out"}]
    report = summarize(manifest(tmp_path, [raw]))
    assert not report["complete"]
    assert report["scansWithDiagnostics"] == 1
    assert report["diagnostics"] == {"total": 1, "unique": 1, "byType": {"Timeout": 1}}
    assert report["scans"][0]["manifestPartial"] is False
    assert report["scans"][0]["partial"] is True


def test_duplicate_counts_and_severity_use_the_same_population(tmp_path):
    raw = document()
    result = {"check_id": "shell", "path": "app.py", "start": {"line": 1, "col": 2},
              "end": {"line": 1, "col": 4}, "extra": {"severity": "ERROR", "metadata": {"category": "security"}}}
    raw["results"] = [result]
    second = deepcopy(raw)
    second["paths"]["scanned"].append("other.py")
    other = deepcopy(result)
    other["start"]["line"] = other["end"]["line"] = 2
    other["extra"]["severity"] = "INFO"
    second["results"].append(other)
    report = summarize(manifest(tmp_path, [raw, second]))
    assert report["complete"]
    assert report["rawFindings"] == {"total": 3, "severity": {"ERROR": 2, "INFO": 1}, "category": {"security": 3}}
    assert report["uniqueFindings"] == {"total": 2, "severity": {"ERROR": 1, "INFO": 1}, "category": {"security": 2}}
    assert report["uniqueFilesReportedScanned"] == 2


@pytest.mark.parametrize("change", ["partial", "exit", "skipped_rule", "skipped_path", "unknown_paths"])
def test_other_coverage_gaps_are_explicit(tmp_path, change):
    raw = document()
    if change == "skipped_rule":
        raw["skipped_rules"] = [{"rule_id": "broken"}]
    elif change == "skipped_path":
        raw["paths"]["skipped"] = [{"path": "huge.py"}]
    elif change == "unknown_paths":
        del raw["paths"]
    path = manifest(tmp_path, [raw])
    data = json.loads(path.read_text())
    if change == "partial":
        data["scans"][0]["partial"] = True
    elif change == "exit":
        data["scans"][0]["exitCode"] = 2
    path.write_text(json.dumps(data))
    assert not summarize(path)["complete"]


@pytest.mark.parametrize("field", ["failed", "skipped", "coveredNothing", "oversized"])
def test_manifest_gaps_are_not_ignored(tmp_path, field):
    assert not summarize(manifest(tmp_path, [document()], **{field: ["gap"]}))["complete"]


@pytest.mark.parametrize("bad", [None, {}, {"results": None}, {"results": [], "errors": "invalid"}])
def test_missing_or_malformed_raw_data_is_an_error(tmp_path, bad):
    path = manifest(tmp_path, [bad])
    if bad is None:
        (tmp_path / "scan-0.json").unlink()
    with pytest.raises((OSError, ValueError)):
        summarize(path)


def test_cli_reports_incomplete_without_modifying_inputs(tmp_path):
    raw = document()
    raw["errors"] = [{"type": "PartialParsing"}]
    path = manifest(tmp_path, [raw])
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    script = Path(__file__).resolve().parents[2] / "tools/summarize_semgrep.py"
    proc = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["complete"] is False
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
