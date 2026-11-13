"""Push notifications reach the UI in the shape it handles.

- Every `run_mapping["..."]` the sidecar uses is defined in mainloop.py. A
  missing key raises KeyError at the moment of the push (it did for the VRAM
  error when enabling translation).
- A missing input device is reported with an error code, so the UI shows its
  translated message rather than the generic "contact the developers" dialog.
"""

import re
import unittest
from pathlib import Path

from config import config
from controller import Controller

SRC = Path(__file__).resolve().parents[1]


def _defined_run_mapping_keys() -> set:
    text = (SRC / "mainloop.py").read_text(encoding="utf-8")
    start = text.index("run_mapping = {")
    end = text.index("\n}\n", start)
    return set(re.findall(r'"(\w+)"\s*:', text[start:end]))


class RunMappingKeysTests(unittest.TestCase):
    def test_every_used_key_is_defined(self) -> None:
        defined = _defined_run_mapping_keys()
        missing = []
        for path in SRC.rglob("*.py"):
            if "test" in path.parts:
                continue
            for key in set(re.findall(r'run_mapping\["(\w+)"\]', path.read_text(encoding="utf-8"))):
                if key not in defined:
                    missing.append(f"{path.relative_to(SRC)}: {key}")
        self.assertEqual(missing, [])


class DeviceErrorPushTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = Controller.__new__(Controller)
        self.controller.run_mapping = {"error_device": "/run/error_device"}
        self.calls = []
        self.controller.run = lambda status, endpoint, result: self.calls.append((status, endpoint, result))
        self._original_sync = config.VRC_MIC_MUTE_SYNC
        config.VRC_MIC_MUTE_SYNC = False

    def tearDown(self) -> None:
        config.VRC_MIC_MUTE_SYNC = self._original_sync

    def test_missing_mic_is_reported_with_its_error_code(self) -> None:
        self.controller.micMessage({"text": False, "language": None})

        status, endpoint, result = self.calls[-1]
        self.assertEqual((status, endpoint), (400, "/run/error_device"))
        self.assertEqual(result["error_code"], "DEVICE_NO_MIC")

    def test_missing_speaker_is_reported_with_its_error_code(self) -> None:
        self.controller.speakerMessage({"text": False, "language": None})

        status, endpoint, result = self.calls[-1]
        self.assertEqual((status, endpoint), (400, "/run/error_device"))
        self.assertEqual(result["error_code"], "DEVICE_NO_SPEAKER")


if __name__ == "__main__":
    unittest.main()
