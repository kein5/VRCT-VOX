"""Real warnings and uncaught exceptions must retain different severities."""
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_warning_is_one_json_line_and_following_exception_is_not_hidden(tmp_path):
    program = '''
import warnings
from sidecar_warnings import format_warning
warnings.formatwarning = format_warning
warnings.warn("first line\\n日本語の次行", FutureWarning)
raise RuntimeError("real failure")
'''
    result = subprocess.run([sys.executable, "-c", program], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ROOT / "src-python")),
                            capture_output=True, text=True, timeout=5)
    lines = result.stderr.splitlines()
    warning = json.loads(lines[0])
    assert warning == {"type": "vrct_warning", "category": "FutureWarning",
                       "message": "first line\n日本語の次行", "filename": "<string>", "lineno": 5}
    assert "Traceback (most recent call last):" == lines[1]
    assert lines[-1] == "RuntimeError: real failure"
    assert result.returncode != 0
    assert result.stdout == ""
