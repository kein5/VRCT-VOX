"""A refused write must fail at once; only a taken name is retried.

tempfile.mkstemp on Windows retried PermissionError while os.access called the folder
writable, which it does whenever the folder is not read-only. A folder whose permissions
refused the write made saveConfigToFile spin about 2**31 times with the config lock held.
"""
import errno
import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

import exclusive_tempfile
from exclusive_tempfile import mkstemp


class ExclusiveTempfileTests(unittest.TestCase):
    def test_creates_a_new_file_next_to_the_target(self):
        with TemporaryDirectory() as directory:
            fd, path = mkstemp(dir=directory, prefix="config.json.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("{}")
            self.assertEqual(os.path.dirname(path), directory)
            self.assertTrue(os.path.basename(path).startswith("config.json."))
            self.assertTrue(path.endswith(".tmp"))
            with open(path, encoding="utf-8") as stream:
                self.assertEqual(stream.read(), "{}")

    def test_refused_write_fails_on_the_first_attempt(self):
        calls = []

        def refuse(path, *args):
            calls.append(path)
            raise PermissionError(errno.EACCES, "denied", path)

        with TemporaryDirectory() as directory, patch.object(exclusive_tempfile.os, "open", refuse):
            with self.assertRaises(PermissionError):
                mkstemp(dir=directory)
        self.assertEqual(len(calls), 1)

    def test_only_a_taken_name_is_tried_again(self):
        real_open = os.open
        calls = []

        def taken_once(path, *args):
            calls.append(path)
            if len(calls) == 1:
                raise FileExistsError(errno.EEXIST, "exists", path)
            return real_open(path, *args)

        with TemporaryDirectory() as directory:
            with patch.object(exclusive_tempfile.os, "open", taken_once):
                fd, path = mkstemp(dir=directory)
            os.close(fd)
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(calls[0], calls[1])
            with patch.object(exclusive_tempfile.os, "open", side_effect=FileExistsError(errno.EEXIST, "exists")):
                with self.assertRaises(FileExistsError):
                    mkstemp(dir=directory)


if __name__ == "__main__":
    unittest.main()
