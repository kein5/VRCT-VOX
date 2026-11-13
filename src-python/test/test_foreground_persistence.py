"""最前面固定 (ENABLE_FOREGROUND) is saved in config.json and read back at startup."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import controller as controller_module
from config import Config


def _isolated_config(path: Path) -> Config:
    instance = object.__new__(Config)
    instance.init_config()
    instance._PATH_CONFIG = str(path)
    return instance


class ForegroundPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "config.json"

    def _load(self, data: dict) -> Config:
        self.path.write_text(json.dumps(data), encoding="utf-8")
        instance = _isolated_config(self.path)
        instance.load_config()
        timer = getattr(instance, "_timer", None)
        if timer is not None:
            self.addCleanup(timer.cancel)
        return instance

    def test_saved_value_is_loaded(self) -> None:
        self.assertIs(self._load({"ENABLE_FOREGROUND": True}).ENABLE_FOREGROUND, True)
        self.assertIs(self._load({}).ENABLE_FOREGROUND, False)

    def test_value_is_written_to_config_json(self) -> None:
        instance = self._load({})
        instance.ENABLE_FOREGROUND = True
        instance.saveConfigToFile()
        self.assertIs(json.loads(self.path.read_text(encoding="utf-8"))["ENABLE_FOREGROUND"], True)

    def test_getter_reports_the_saved_value(self) -> None:
        self.assertEqual(controller_module._SIMPLE_CONFIG_GETTERS["getEnableForeground"], "ENABLE_FOREGROUND")
        original = controller_module.config
        controller_module.config = SimpleNamespace(ENABLE_FOREGROUND=True)
        try:
            app = controller_module.Controller.__new__(controller_module.Controller)
            self.assertEqual(app.getEnableForeground(), {"status": 200, "result": True})
        finally:
            controller_module.config = original


if __name__ == "__main__":
    unittest.main()
