"""The functional specification's reference tables match the code."""
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/spec_catalog.py"


class SpecCatalogTests(unittest.TestCase):
    def test_reference_tables_are_current(self):
        run = subprocess.run([sys.executable, str(SCRIPT), "--check"], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr or run.stdout)

    def test_every_table_lists_entries(self):
        reference = ROOT / "docs/spec/reference"
        for name, heading in (("ipc-endpoints.md", "## 要求"), ("error-codes.md", "## コード"),
                              ("config-keys.md", "## config.jsonに保存するキー")):
            text = (reference / name).read_text(encoding="utf-8")
            self.assertIn(heading, text, name)
            self.assertGreater(text.count("\n| `"), 10, name)


if __name__ == "__main__":
    unittest.main()
