"""Startup policy and isolated launch wiring; no GUI, D-Bus or sockets."""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


class SingleInstanceTests(unittest.TestCase):
    def test_single_instance_is_registered_before_other_plugins_and_setup(self):
        source = (ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
        plugins = re.findall(r"\.plugin\(\s*(\w+)::", source)
        self.assertEqual(plugins[0], "tauri_plugin_single_instance")
        self.assertLess(source.index("tauri_plugin_single_instance::init"), source.index(".setup("))
        self.assertRegex(source, r"single_instance_enabled\(\s*cfg!\(debug_assertions\),\s*"
                         r'std::env::var_os\("VRCT_CONFIG_DIR"\)\.as_deref\(\)')

    @unittest.skipUnless(shutil.which("rustc"), "requires rustc for the startup policy unit tests")
    def test_rust_single_instance_policy(self):
        with tempfile.TemporaryDirectory(prefix="vox single instance ") as directory:
            binary = Path(directory) / ("policy.exe" if os.name == "nt" else "policy")
            subprocess.run([shutil.which("rustc"), "--edition=2021", "--test",
                            str(ROOT / "src-tauri/src/single_instance.rs"), "-o", str(binary)],
                           check=True, timeout=60)
            subprocess.run([str(binary)], check=True, timeout=10)


class NativeLaunchEnvironmentTests(unittest.TestCase):
    def launch_environment(self, inherited=None, extra=None):
        spec = importlib.util.spec_from_file_location("native_launch", ROOT / "tests/platform/native_webdriver.py")
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        directory = tempfile.TemporaryDirectory(prefix="vox isolated launch ")
        self.addCleanup(directory.cleanup)
        output = Path(directory.name)
        driver = native.NativeWebDriver(output, extra)

        class LaunchIntercepted(Exception):
            pass

        # Stop at the process boundary, before tauri-driver or the app can start.
        with patch.dict(os.environ, inherited or {}, clear=True), \
                patch.object(native, "check_displays_on"), \
                patch.object(native.socket, "socket") as socket, \
                patch.object(native.subprocess, "Popen", side_effect=LaunchIntercepted) as launch:
            socket.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 12345)
            try:
                with self.assertRaises(LaunchIntercepted):
                    driver.__enter__()
            finally:
                if hasattr(driver, "log"):
                    driver.log.close()
        return output, launch.call_args.kwargs["env"]

    def test_default_launch_bypasses_single_instance_without_moving_xdg_state(self):
        output, env = self.launch_environment()
        self.assertEqual(env.get("VRCT_CONFIG_DIR"), str(output / "config/vrct-vox"))
        self.assertEqual(Path(env["VRCT_CONFIG_DIR"]), Path(env["XDG_CONFIG_HOME"]) / "vrct-vox")
        self.assertEqual(env["XDG_DATA_HOME"], str(output / "data"))
        self.assertEqual(env["XDG_CACHE_HOME"], str(output / "cache"))

    def test_caller_config_directory_overrides_inherited_state(self):
        _, env = self.launch_environment({"VRCT_CONFIG_DIR": "/inherited/state"},
                                         {"VRCT_CONFIG_DIR": "/caller/state with spaces"})
        self.assertEqual(env["VRCT_CONFIG_DIR"], "/caller/state with spaces")

    def test_inherited_config_directory_is_preserved(self):
        _, env = self.launch_environment({"VRCT_CONFIG_DIR": "/inherited/state"})
        self.assertEqual(env["VRCT_CONFIG_DIR"], "/inherited/state")
