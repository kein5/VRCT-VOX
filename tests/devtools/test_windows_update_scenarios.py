"""Offline checks of the fixtures used by the real Windows installer job."""

import importlib.util
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock
import zipfile


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "windows_update_scenarios", ROOT / "tests/installer/windows_update_scenarios.py")
scenarios = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenarios)


class WindowsUpdateFixtureTests(unittest.TestCase):
    def test_valid_archives_have_exact_app_owned_top_level(self):
        for version in ("old", "new"):
            with self.subTest(version=version), zipfile.ZipFile(io.BytesIO(scenarios.payloads()[version])) as archive:
                self.assertEqual({name.split("/")[0] for name in archive.namelist()},
                                 {scenarios.APP, scenarios.SIDECAR, "_internal"})
                self.assertIsNone(archive.testzip())

    def test_partial_archive_breaks_after_main_and_some_dependencies(self):
        with zipfile.ZipFile(io.BytesIO(scenarios.payloads()["partial"])) as archive:
            self.assertEqual(archive.read(scenarios.APP), scenarios.payload_files("new")[scenarios.APP])
            self.assertEqual(archive.read("_internal/shared.txt"), b"new dependency")
            with self.assertRaises(zipfile.BadZipFile):
                archive.read("_internal/new-only.txt")

    def test_missing_component_archives_are_otherwise_valid(self):
        for version, missing in (("no-exe", scenarios.APP), ("no-internal", "_internal/")):
            with self.subTest(version=version), zipfile.ZipFile(io.BytesIO(scenarios.payloads()[version])) as archive:
                self.assertFalse(any(name.startswith(missing) for name in archive.namelist()))
                self.assertIsNone(archive.testzip())

    def request(self, version, filename, range_header=None, head=False):
        handler = object.__new__(scenarios.PackageHandler)
        handler.path = f"/v{version}/{filename}"
        handler.command = "HEAD" if head else "GET"
        handler.headers = {"Range": range_header} if range_header else {}
        handler.server = SimpleNamespace(payloads=scenarios.payloads(), requests=[], request_lock=threading.Lock())
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.send_error = Mock()
        handler.respond(head)
        return handler

    def test_head_advertises_full_size_without_sending_body(self):
        handler = self.request("new", scenarios.PACKAGE, head=True)
        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Length", str(len(scenarios.payloads()["new"])))
        self.assertEqual(handler.wfile.getvalue(), b"")

    def test_range_returns_requested_bytes_and_content_range(self):
        handler = self.request("new", scenarios.PACKAGE, "bytes=10-29")
        handler.send_response.assert_called_once_with(206)
        handler.send_header.assert_any_call("Content-Range", f"bytes 10-29/{len(scenarios.payloads()['new'])}")
        self.assertEqual(handler.wfile.getvalue(), scenarios.payloads()["new"][10:30])

    def test_range_failure_does_not_break_single_connection(self):
        handler = self.request("range-fallback", scenarios.PACKAGE, "bytes=0-29")
        handler.send_error.assert_called_once_with(416)
        handler = self.request("range-fallback", scenarios.PACKAGE)
        handler.send_response.assert_called_once_with(200)
        self.assertEqual(handler.wfile.getvalue(), scenarios.payloads()["new"])

    def test_checksum_faults_are_distinct(self):
        filename = scenarios.PACKAGE + ".sha256"
        self.request("checksum-404", filename).send_error.assert_called_once_with(404)
        self.assertEqual(self.request("invalid-checksum", filename).wfile.getvalue(), b"invalid")
        self.assertEqual(self.request("hash-mismatch", filename).wfile.getvalue(), b"0" * 64)
        expected = scenarios.sha256(scenarios.payloads()["partial"]).hexdigest().encode()
        self.assertEqual(self.request("partial", filename).wfile.getvalue(), expected)

    def test_full_tree_comparison_catches_extra_empty_directories(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "file").write_bytes(b"original")
            before = scenarios.snapshot(path)
            (path / "extra").mkdir()
            with self.assertRaises(AssertionError):
                scenarios.assert_tree(path, before)

    def test_installer_directory_argument_is_last_and_unquoted(self):
        command = scenarios.installer_command("C:/test/setup.exe", "C:/test/install dir", "new")
        self.assertIn("/S /NS /UILANG=en /VERSION=new", command)
        self.assertTrue(command.endswith(" /D=C:/test/install dir"))


if __name__ == "__main__":
    unittest.main()
