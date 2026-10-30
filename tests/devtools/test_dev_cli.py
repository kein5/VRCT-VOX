"""Offline contracts for the developer entry point; no product imports."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/dev.py"


class DeveloperCLITests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "developer entry point is missing")
        spec = importlib.util.spec_from_file_location("vox_dev_cli", SCRIPT)
        self.dev = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.dev
        spec.loader.exec_module(self.dev)
        self.tmp = tempfile.TemporaryDirectory(prefix="vox dev tests ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "package.json").write_text('{"name":"vrct-vox"}')
        (self.root / "package-lock.json").write_text('{}')
        (self.root / "requirements-voice-test.txt").write_text('pytest==8.4.2\n')

    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = self.dev.main(list(args), root=self.root)
        return code, output.getvalue()

    def test_doctor_reports_missing_environment_without_installing(self):
        with patch.dict(os.environ, {"PATH": ""}):
            code, output = self.call("doctor", "--scope", "voice", "--json")
        self.assertEqual(code, 2)
        report = json.loads(output)
        self.assertFalse(report["ok"])
        self.assertTrue(any(row["status"] == "missing" for row in report["checks"]))
        self.assertIn("setup --scope headless", output)
        self.assertFalse((self.root / "build").exists())

    def test_dry_setup_can_be_reviewed_before_tools_are_installed(self):
        with patch.dict(os.environ, {"PATH": ""}):
            code, output = self.call("setup", "--scope", "headless", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("requirements-voice-test.txt", output)
        self.assertIn("--python", output)
        self.assertFalse((self.root / "build").exists())

    def test_headless_resolves_transitive_dependencies_from_non_lock_requirements(self):
        # pytest needs pluggy/packaging: pip sync accepts a complete lock and
        # would leave this existing direct-only requirements list incomplete.
        code, output = self.call("setup", "--scope", "headless", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("pip install", output)

    def test_missing_python_dependency_is_a_prerequisite_error(self):
        target = self.root / "build/dev/headless-venv"
        python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        python.parent.mkdir(parents=True)
        python.write_text("")
        with patch.object(self.dev, "probe", return_value=subprocess.CompletedProcess(
            [], 1, '', 'PackageNotFoundError: pytest')):
            code, output = self.call("check", "--scope", "voice")
        self.assertEqual(code, 2)
        self.assertIn("setup --scope headless", output)

    def test_setup_refuses_unowned_environment_without_deleting_it(self):
        target = self.root / "build/dev/headless-venv"
        target.mkdir(parents=True)
        sentinel = target / "user-data"
        sentinel.write_bytes(b"keep me")
        code, output = self.call("setup", "--scope", "headless")
        self.assertEqual(code, 2)
        self.assertIn("owned", output)
        self.assertEqual(sentinel.read_bytes(), b"keep me")

    @unittest.skipIf(os.name == "nt", "symlinks require Windows privilege")
    def test_setup_refuses_symlinked_parent(self):
        external = self.root / "elsewhere"
        external.mkdir()
        (self.root / "build").symlink_to(external, target_is_directory=True)
        code, _ = self.call("setup", "--scope", "headless")
        self.assertEqual(code, 2)
        self.assertEqual(list(external.iterdir()), [])

    def test_node_scope_discovers_new_tests_without_shell_globs(self):
        folder = self.root / "src-ui/area with spaces"
        folder.mkdir(parents=True)
        for name in ("one.test.js", "future.test.mjs"):
            (folder / name).write_text('')
        code, output = self.call("check", "--scope", "node", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("one.test.js", output)
        self.assertIn("future.test.mjs", output)
        self.assertNotIn("npm ci", output)

    def test_node_scope_does_not_pass_when_no_tests_were_found(self):
        code, output = self.call("check", "--scope", "node", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("No Node tests", output)

    def test_rust_check_uses_only_locked_cached_dependencies(self):
        code, output = self.call("check", "--scope", "rust", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("--offline", output)
        self.assertIn("--locked", output)
        self.assertNotIn("cargo fetch", output)

    def test_browser_setup_adds_dependencies_to_explicit_existing_python(self):
        code, output = self.call("setup", "--scope", "browser", "--python",
            sys.executable, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("requirements-voice-ui-test.txt", output)
        self.assertIn("pip install", output)
        self.assertNotIn("pip sync", output)
        self.assertNotIn("--with-deps", output)

    def test_browser_setup_refuses_system_interpreter(self):
        with patch.object(self.dev, "probe", return_value=subprocess.CompletedProcess(
            [], 0, '{"venv":false,"version":[3,11]}', '')), \
                patch.object(self.dev, "execute", return_value=0):
            code, output = self.call("setup", "--scope", "browser", "--python", sys.executable)
        self.assertEqual(code, 2)
        self.assertIn("virtual environment", output)

    def test_browser_doctor_selects_browser_environment(self):
        target = self.root / "build/dev/browser-venv"
        python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        python.parent.mkdir(parents=True)
        python.write_text("")
        with patch.object(self.dev, "probe", return_value=subprocess.CompletedProcess(
            [], 0, '3.11.17\npytest 8.4.2\nplaywright 1.64.1', '')):
            code, output = self.call("doctor", "--scope", "browser", "--json")
        self.assertEqual(code, 0, output)

    def test_linux_tray_library_accepts_either_provider_but_not_neither(self):
        binary = self.root / "src-tauri/bin/vrct-vox-sidecar-x86_64-unknown-linux-gnu"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"existing sidecar")
        resources = binary.parent / "_internal"
        resources.mkdir()
        (resources / "resource").write_text("existing")
        for available in ("appindicator3-0.1", "ayatana-appindicator3-0.1", None):
            with self.subTest(available=available):
                def lookup(argv, root):
                    if "-vV" in argv:
                        return subprocess.CompletedProcess(argv, 0, "host: x86_64-unknown-linux-gnu\n", "")
                    if argv[0] == "pkg-config":
                        missing = argv[-1] in ("appindicator3-0.1", "ayatana-appindicator3-0.1") and argv[-1] != available
                        return subprocess.CompletedProcess(argv, int(missing), "", "")
                    return subprocess.CompletedProcess(argv, 0, "cargo 1.99.1", "")
                with patch.object(self.dev.sys, "platform", "linux"), \
                        patch.object(self.dev.shutil, "which", side_effect=lambda name: name), \
                        patch.object(self.dev, "probe", side_effect=lookup):
                    code, output = self.call("doctor", "--scope", "rust", "--json")
                self.assertEqual(code, 0 if available else 2, output)
                if available:
                    self.assertIn(available, output)

    def test_commits_requires_explicit_base_instead_of_scanning_old_history(self):
        code, output = self.call("check", "--scope", "commits", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("--base", output)

    def test_unknown_base_is_not_treated_as_empty_success(self):
        code, _ = self.call("check", "--scope", "commits", "--base", "missing-base")
        self.assertEqual(code, 2)

    def test_tooling_does_not_inherit_live_acceptance_flags(self):
        test_dir = self.root / "tests/devtools"
        test_dir.mkdir(parents=True)
        (test_dir / "test_probe.py").write_text(
            'import os, unittest\n'
            'class Probe(unittest.TestCase):\n'
            ' def test_environment(self):\n'
            '  self.assertNotIn("VRCT_SEED_POC", os.environ)\n'
            '  self.assertNotIn("VRCT_TEST_NATIVE_GUI", os.environ)\n'
            '  self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")\n'
            '  self.assertNotIn("PYTEST_ADDOPTS", os.environ)\n',
            encoding="utf8",
        )
        with patch.dict(os.environ, {
            "VRCT_SEED_POC": "never-start", "VRCT_TEST_NATIVE_GUI": "1",
            "PYTEST_ADDOPTS": "--unwanted", "HF_HUB_OFFLINE": "0",
        }):
            code, _ = self.call("check", "--scope", "tooling")
        self.assertEqual(code, 0)

    def test_failure_stops_plan_and_propagates_nonzero_exit(self):
        marker = self.root / "must-not-exist"
        steps = [
            self.dev.Step("failure", [sys.executable, "-c", "raise SystemExit(7)"]),
            self.dev.Step("later", [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            code = self.dev.execute(steps, self.root, dry_run=False)
        self.assertEqual(code, 1)
        self.assertFalse(marker.exists())

    def test_child_receives_space_and_shell_characters_as_one_argument(self):
        value = "path with spaces;$(not-a-command)"
        step = self.dev.Step("argv", [sys.executable, "-c",
            "import sys; assert sys.argv[1] == 'path with spaces;$(not-a-command)'", value])
        with contextlib.redirect_stdout(io.StringIO()):
            code = self.dev.execute([step], self.root, dry_run=False)
        self.assertEqual(code, 0)

    def test_help_runs_without_site_packages(self):
        result = subprocess.run([sys.executable, "-S", str(SCRIPT), "--help"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("doctor", result.stdout)
        self.assertIn("check", result.stdout)


if __name__ == "__main__":
    unittest.main()
