"""An unreadable config.json is kept, not overwritten with defaults.

load_config() ends by saving the whole config. When config.json could not
be parsed, that save used to replace the user's only copy of their settings
and API keys with defaults.
"""

import json
import tempfile
import unittest
from pathlib import Path

from config import Config


def _isolated_config(path: Path) -> Config:
    instance = object.__new__(Config)
    instance.init_config()
    instance._PATH_CONFIG = str(path)
    return instance


class UnreadableConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "config.json"

    def _load(self, text: str) -> Config:
        self.path.write_text(text, encoding="utf-8")
        instance = _isolated_config(self.path)
        instance.load_config()
        timer = getattr(instance, "_timer", None)
        if timer is not None:
            self.addCleanup(timer.cancel)
        return instance

    def test_broken_json_is_moved_aside_and_kept(self) -> None:
        broken = '{"UI_LANGUAGE": "ja", "AUTH_KEYS": {"DeepL_API": "secret"'
        instance = self._load(broken)

        backup = Path(instance.UNREADABLE_CONFIG_BACKUP)
        self.assertEqual(backup.parent, self.path.parent)
        self.assertTrue(backup.name.startswith("config.json.unreadable-"))
        self.assertEqual(backup.read_text(encoding="utf-8"), broken)
        # A fresh, readable config.json replaces it.
        self.assertIsInstance(json.loads(self.path.read_text(encoding="utf-8")), dict)

    def test_json_that_is_not_an_object_is_moved_aside(self) -> None:
        instance = self._load("[1, 2, 3]")

        self.assertIsNotNone(instance.UNREADABLE_CONFIG_BACKUP)
        self.assertEqual(Path(instance.UNREADABLE_CONFIG_BACKUP).read_text(encoding="utf-8"), "[1, 2, 3]")

    def test_readable_config_is_loaded_and_not_moved(self) -> None:
        instance = self._load(json.dumps({"UI_LANGUAGE": "ja"}))

        self.assertIsNone(instance.UNREADABLE_CONFIG_BACKUP)
        self.assertEqual(instance.UI_LANGUAGE, "ja")
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["config.json", "config.json.lock"])


if __name__ == "__main__":
    unittest.main()
