"""Optional native VC tests must be importable without Unix audio dependencies."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("name", ["test_native_vc_worker.py", "test_native_direct_vc.py"])
def test_native_vc_collection_does_not_require_fcntl(name):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c",
         "import runpy, sys; sys.modules['fcntl'] = None; runpy.run_path(sys.argv[1])",
         str(root / "tests/platform" / name)],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": os.pathsep.join(
            str(root / path) for path in (".", "src-python", "tests/platform"))},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
