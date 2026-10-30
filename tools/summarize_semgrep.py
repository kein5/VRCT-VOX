#!/usr/bin/env python3
"""Audit an existing scans.json and raw JSON files without running Semgrep.

Print a JSON report; exit 0 for complete recorded coverage, 1 for coverage gaps,
and 2 for invalid/missing input. No artifacts are changed. 'complete' describes
the supplied scan plan, not whether it covers every language or vulnerability.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


def _array(obj: dict, name: str, *, required: bool = False) -> list:
    value = obj.get(name, None if required else [])
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _counts(findings: list[dict]) -> dict:
    return {
        "total": len(findings),
        "severity": dict(sorted(Counter(item["severity"] for item in findings).items())),
        "category": dict(sorted(Counter(item["category"] for item in findings).items())),
    }


def summarize(manifest: Path) -> dict:
    """Keep diagnostic coverage separate from findings and raw/unique totals."""
    manifest = manifest.resolve()
    data = _load(manifest)
    rows = _array(data, "scans", required=True)
    gaps = {name: _array(data, name) for name in ("failed", "skipped", "coveredNothing", "oversized")}
    complete = bool(rows) and not any(gaps.values())
    scans, findings, diagnostics = [], [], []
    files, unique = set(), {}
    for scan in rows:
        if not isinstance(scan, dict) or not isinstance(scan.get("json"), str):
            raise ValueError("each scan must identify a raw JSON file")
        raw_path = manifest.parent / scan["json"]
        raw = _load(raw_path)
        results = _array(raw, "results", required=True)
        errors = _array(raw, "errors", required=True)
        skipped_rules = _array(raw, "skipped_rules")
        paths = raw.get("paths", {})
        if not isinstance(paths, dict):
            raise ValueError(f"{raw_path}: paths must be an object")
        scanned = paths.get("scanned")
        if scanned is not None:
            if not isinstance(scanned, list) or any(not isinstance(p, str) for p in scanned):
                raise ValueError(f"{raw_path}: paths.scanned must be an array of strings")
            files.update(scanned)
        skipped_paths = _array(paths, "skipped")
        partial = bool(scan.get("partial") or errors or skipped_rules or skipped_paths
                       or not scanned or scan.get("exitCode") not in (0, 1))
        complete = complete and not partial
        for error in errors:
            if not isinstance(error, dict):
                raise ValueError(f"{raw_path}: invalid diagnostic")
        diagnostics.extend(errors)
        scans.append({
            "ruleset": scan.get("ruleset"), "json": str(raw_path),
            "exitCode": scan.get("exitCode"), "manifestPartial": scan.get("partial"),
            "partial": partial, "diagnostics": errors,
            "skippedRules": skipped_rules, "skippedPaths": skipped_paths,
            "filesReportedScanned": len(scanned) if scanned is not None else None,
        })
        for result in results:
            try:
                start, end = result["start"], result["end"]
                key = (result["check_id"], result["path"], start["line"], start["col"], end["line"], end["col"])
                extra = result["extra"]
                item = {"rule": key[0], "path": key[1], "start": start, "end": end,
                        "severity": extra["severity"], "category": extra.get("metadata", {}).get("category", "UNSET")}
            except (KeyError, TypeError) as exc:
                raise ValueError(f"{raw_path}: invalid finding") from exc
            findings.append(item)
            if key in unique and any(unique[key][field] != item[field] for field in ("severity", "category")):
                raise ValueError(f"conflicting metadata for duplicate finding: {key}")
            unique[key] = item
    types = Counter()
    for error in diagnostics:
        kind = error.get("type", "UNSET")
        # Some Semgrep versions encode tagged error types as [name, payload].
        types[str(kind[0] if isinstance(kind, list) and kind else kind)] += 1
    return {
        "manifest": str(manifest), "complete": bool(complete), "manifestGaps": gaps,
        "scanCount": len(scans), "scansWithDiagnostics": sum(bool(s["diagnostics"]) for s in scans),
        "uniqueFilesReportedScanned": len(files),
        "rawFindings": _counts(findings), "uniqueFindings": _counts(list(unique.values())),
        "diagnostics": {"total": len(diagnostics),
                        "unique": len({json.dumps(e, sort_keys=True) for e in diagnostics}),
                        "byType": dict(sorted(types.items()))},
        "scans": scans, "findings": list(unique.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Existing scans.json")
    args = parser.parse_args()
    try:
        report = summarize(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"Semgrep report error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
