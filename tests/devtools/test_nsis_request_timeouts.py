"""Installer command bounds, inspected without executing the installer."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


class NsisRequestTimeoutTests(unittest.TestCase):
    def test_every_curl_command_has_connect_and_total_limits(self):
        source = (ROOT / "src-tauri/nsis/template.nsi").read_text(encoding="utf-8")
        commands = [line for line in source.splitlines()
                    if not line.lstrip().startswith(";") and "curl.exe" in line]
        self.assertTrue(commands, "The package metadata probe must be covered")
        for command in commands:
            with self.subTest(command=command):
                connect = re.search(r"--connect-timeout\s+(\d+)\b", command)
                total = re.search(r"--max-time\s+(\d+)\b", command)
                self.assertIsNotNone(connect)
                self.assertIsNotNone(total)
                self.assertGreater(int(connect[1]), 0)
                self.assertLessEqual(int(connect[1]), 10)
                self.assertGreaterEqual(int(total[1]), int(connect[1]))
                self.assertLessEqual(int(total[1]), 30)
                if "--retry " in command:
                    self.assertRegex(command, r"--retry-max-time\s+30\b")
