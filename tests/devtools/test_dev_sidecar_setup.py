"""Sidecar preparation only: no real app, microphone, models, or GPU."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


class SidecarSetupTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("vox_dev_sidecar_setup", ROOT / "tools/dev.py")
        self.dev = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.dev
        spec.loader.exec_module(self.dev)
        self.assertIn("sidecar", self.dev.SETUP_SCOPES, "explicit sidecar setup missing")
        self.tmp = tempfile.TemporaryDirectory(prefix="vox sidecar test ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "utils/dev_sidecar/src/main.rs"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("fn main() {}")
        self.host = "x86_64-unknown-linux-gnu"
        self.target = self.root / "src-tauri/bin" / ("vrct-vox-sidecar-" + self.host)
        self.payload = b"first owned compiler output"

    def compiler(self, argv, **kwargs):
        if "-vV" in argv:
            return subprocess.CompletedProcess(argv, 0, "rustc version\nhost: " + self.host + "\n", "")
        self.assertEqual(argv[1:3], ["--edition=2021", "--crate-name"])
        self.assertIn(str(self.source), argv)
        self.assertFalse(kwargs.get("shell", False))
        Path(argv[argv.index("-o") + 1]).write_bytes(self.payload)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def run_setup(self, compiler=None, dry_run=False):
        output = io.StringIO()
        with patch.object(self.dev.sys, "platform", "linux"), \
                patch.object(self.dev.subprocess, "run", side_effect=compiler or self.compiler), \
                patch.object(self.dev.shutil, "which", return_value="rustc"), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = self.dev.main(["setup", "--scope", "sidecar", *(["--dry-run"] if dry_run else [])], root=self.root)
        return code, output.getvalue()

    def test_new_wrapper_has_ownership_and_marked_resources(self):
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertTrue(list(self.target.parent.glob("*.dev-owner.json")))
        internal = self.target.parent / "_internal"
        self.assertTrue((internal / ".vrct-vox-dev-placeholder").is_file())

    def test_rebuild_preserves_resources_and_atomically_changes_owned_binary(self):
        code, _ = self.run_setup()
        self.assertEqual(code, 0)
        preserved = self.target.parent / "_internal/user-file"
        preserved.write_bytes(b"do not replace resources")
        self.payload = b"next compiler output"
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(preserved.read_bytes(), b"do not replace resources")

    def test_unknown_existing_binary_is_never_claimed(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"production frozen backend")
        code, output = self.run_setup()
        self.assertEqual(code, 2, output)
        self.assertEqual(self.target.read_bytes(), b"production frozen backend")
        self.assertFalse(list(self.target.parent.glob("*.dev-owner.json")))

    def test_existing_production_resources_are_not_marked_or_changed(self):
        resources = self.target.parent / "_internal"
        resources.mkdir(parents=True)
        (resources / "frozen-runtime").write_bytes(b"keep production runtime")
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertEqual(list(p.name for p in resources.iterdir()), ["frozen-runtime"])
        self.assertEqual((resources / "frozen-runtime").read_bytes(), b"keep production runtime")

    def test_existing_empty_resources_get_an_exclusive_placeholder(self):
        resources = self.target.parent / "_internal"
        resources.mkdir(parents=True)
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        marker = resources / ".vrct-vox-dev-placeholder"
        self.assertTrue(marker.is_file(), "empty existing resources need a development placeholder")
        marker.write_bytes(b"preserve an existing marker")
        self.assertEqual(self.run_setup()[0], 0)
        self.assertEqual(marker.read_bytes(), b"preserve an existing marker")

    def test_rust_doctor_reports_missing_sidecar_and_resources(self):
        def missing_inputs(argv, root):
            return subprocess.CompletedProcess(argv, 0,
                "host: x86_64-unknown-linux-gnu\n" if "-vV" in argv else "cargo 1.99.1", "")
        output = io.StringIO()
        with patch.object(self.dev.sys, "platform", "linux"), \
                patch.object(self.dev.shutil, "which", side_effect=lambda name: name), \
                patch.object(self.dev, "probe", side_effect=missing_inputs), \
                contextlib.redirect_stdout(output):
            code = self.dev.main(["doctor", "--scope", "rust", "--json"], root=self.root)
        self.assertEqual(code, 2)
        report = json.loads(output.getvalue())
        missing = {r["name"] for r in report["checks"] if r["status"] == "missing"}
        self.assertEqual(missing, {"Tauri external sidecar", "Tauri resources"})
        self.assertIn("setup --scope sidecar", output.getvalue())

    def test_hash_mismatch_after_compile_stops_publication(self):
        self.assertEqual(self.run_setup()[0], 0)

        def racing_compiler(argv, **kwargs):
            result = self.compiler(argv, **kwargs)
            if "-o" in argv:
                self.target.write_bytes(b"another session's new file")
            return result

        code, output = self.run_setup(racing_compiler)
        self.assertEqual(code, 2, output)
        self.assertEqual(self.target.read_bytes(), b"another session's new file")

    def test_compiler_failure_preserves_binary_and_owner_record(self):
        self.assertEqual(self.run_setup()[0], 0)
        record = next(self.target.parent.glob("*.dev-owner.json"))
        before = (self.target.read_bytes(), record.read_bytes())

        def failed_compiler(argv, **kwargs):
            if "-vV" in argv:
                return self.compiler(argv, **kwargs)
            return subprocess.CompletedProcess(argv, 1, "", "synthetic compiler failure")

        code, output = self.run_setup(failed_compiler)
        self.assertEqual(code, 1, output)
        self.assertEqual((self.target.read_bytes(), record.read_bytes()), before)

    def test_interrupted_marker_finalization_can_retry_owned_binary(self):
        self.assertEqual(self.run_setup()[0], 0)
        self.payload = b"new atomically published binary"
        replace = self.dev.os.replace
        marker_writes = 0

        def interrupted_replace(source, target):
            nonlocal marker_writes
            if str(target).endswith(".dev-owner.json"):
                marker_writes += 1
                if marker_writes == 2:
                    raise OSError("marker write interrupted")
            return replace(source, target)

        with patch.object(self.dev.os, "replace", side_effect=interrupted_replace):
            code, _ = self.run_setup()
        self.assertEqual(code, 2)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(self.run_setup()[0], 0)

    @unittest.skipIf(os.name == "nt", "symlink privilege")
    def test_symlink_output_parent_is_refused(self):
        external = self.root / "elsewhere"
        external.mkdir()
        (self.root / "src-tauri").symlink_to(external, target_is_directory=True)
        code, output = self.run_setup()
        self.assertEqual(code, 2, output)
        self.assertEqual(list(external.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "symlink privilege")
    def test_symlink_binary_is_not_followed_or_replaced(self):
        external = self.root / "production-binary"
        external.write_bytes(b"do not replace")
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(external)
        code, _ = self.run_setup()
        self.assertEqual(code, 2)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(external.read_bytes(), b"do not replace")

    def test_malicious_host_triple_is_not_used_as_a_path(self):
        self.host = "../../outside"
        code, output = self.run_setup()
        self.assertEqual(code, 2, output)
        self.assertFalse((self.root / "src-tauri").exists())

    def test_dry_run_does_not_create_binary_or_resources(self):
        code, output = self.run_setup(dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertFalse((self.root / "src-tauri").exists())

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("rustc"), "real Unix rustc needed")
    def test_real_wrapper_forwards_arguments_only_to_owned_fake_workload(self):
        shutil.copyfile(ROOT / "utils/dev_sidecar/src/main.rs", self.source)
        script = self.root / "src-python/mainloop.py"
        script.parent.mkdir(parents=True)
        script.write_text("import json,sys; print(json.dumps(sys.argv[1:]))", encoding="utf8")
        python = self.root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        with contextlib.redirect_stdout(io.StringIO()):
            code = self.dev.main(["setup", "--scope", "sidecar"], root=self.root)
        self.assertEqual(code, 0)
        binary = next(self.target.parent.glob("vrct-vox-sidecar-*"))
        if binary.suffix == ".json":
            binary = next(p for p in self.target.parent.glob("vrct-vox-sidecar-*") if p.suffix != ".json")
        env = {k: v for k, v in os.environ.items() if k != "VRCT_DEV_VENV"}
        result = subprocess.run([str(binary), "日本語", "argument with spaces;$(literal)"],
            env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["日本語", "argument with spaces;$(literal)"])


if __name__ == "__main__":
    unittest.main()
