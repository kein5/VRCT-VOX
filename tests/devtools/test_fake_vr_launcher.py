"""tools/run_with_fake_vr.py: only the backend gets the fake SteamVR, and a failed
injection never stops it from starting."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import run_with_fake_vr  # noqa: E402


class FakeVrLauncherTests(unittest.TestCase):
    def test_environment_puts_the_site_first_and_names_the_output(self):
        env = run_with_fake_vr.environment(Path("out"), {"PYTHONPATH": "existing", "OTHER": "kept"})
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep), [str(run_with_fake_vr.SITE), "existing"])
        self.assertEqual(env["VOX_FAKE_VR_OUT"], "out")
        self.assertEqual(env["OTHER"], "kept")

    def run_script(self, name):
        with tempfile.TemporaryDirectory(prefix="vox fake vr ") as directory:
            script = Path(directory) / name
            script.write_text("print('started')\n", encoding="utf-8")
            env = run_with_fake_vr.environment(Path(directory) / "out")
            return subprocess.run([sys.executable, str(script)], env=env, capture_output=True,
                                  text=True, timeout=60)

    def test_other_python_processes_are_left_alone(self):
        result = self.run_script("task_kill.py")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "started")
        self.assertNotIn("fake", result.stderr)

    def test_backend_starts_even_when_the_fake_cannot_be_loaded(self):
        # This interpreter has no pyopenvr/numpy (or has them, and then the fake
        # loads). Either way mainloop.py itself must still run.
        result = self.run_script("mainloop.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "started")


if __name__ == "__main__":
    unittest.main()
