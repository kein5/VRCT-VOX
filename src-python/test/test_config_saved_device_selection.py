"""手動で選んだマイクとスピーカーが、起動のたびに既定のデバイスへ戻らない。

config.json を読む時点では、デバイスの一覧がまだ取れていない (device_manager は
監視スレッドの最初の更新で一覧を埋める)。以前は保存した選択をこの空の一覧で
検証して拒否し、そのあと controller が既定のデバイスを選んで保存していた。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config as config_module
from config import Config


class _Devices:
    def __init__(self, mic: dict, speakers: list) -> None:
        self.mic = mic
        self.speakers = speakers

    def getMicDevices(self):
        return self.mic

    def getSpeakerDevices(self):
        return self.speakers

    def getDefaultMicDevice(self):
        return {"host": {"name": "NoHost"}, "device": {"name": "NoDevice"}}

    def getDefaultSpeakerDevice(self):
        return {"device": {"name": "NoDevice"}}


_NOT_LISTED_YET = _Devices({"NoHost": [{"index": -1, "name": "NoDevice"}]}, [{"index": -1, "name": "NoDevice"}])
_SAVED = {"SELECTED_MIC_HOST": "PipeWire", "SELECTED_MIC_DEVICE": "USB Mic", "SELECTED_SPEAKER_DEVICE": "Headphones"}


class SavedDeviceSelectionTests(unittest.TestCase):
    def _load(self, devices: _Devices) -> Config:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.json"
        path.write_text(json.dumps(_SAVED), encoding="utf-8")
        with patch.object(config_module, "device_manager", devices), patch.object(config_module, "errorLogging"):
            instance = object.__new__(Config)
            instance.init_config()
            instance._PATH_CONFIG = str(path)
            instance.load_config()
        timer = getattr(instance, "_timer", None)
        if timer is not None:
            self.addCleanup(timer.cancel)
        return instance

    def test_saved_selection_is_kept_while_devices_are_not_listed(self) -> None:
        instance = self._load(_NOT_LISTED_YET)

        self.assertEqual(instance.SELECTED_MIC_HOST, "PipeWire")
        self.assertEqual(instance.SELECTED_MIC_DEVICE, "USB Mic")
        self.assertEqual(instance.SELECTED_SPEAKER_DEVICE, "Headphones")

    def test_listed_devices_still_reject_a_missing_selection(self) -> None:
        listed = _Devices({"PipeWire": [{"index": 0, "name": "Built-in Mic"}]}, [{"index": 0, "name": "Speakers"}])
        instance = self._load(listed)

        self.assertEqual(instance.SELECTED_MIC_HOST, "PipeWire")
        self.assertNotEqual(instance.SELECTED_MIC_DEVICE, "USB Mic")
        self.assertNotEqual(instance.SELECTED_SPEAKER_DEVICE, "Headphones")

    def test_settings_changed_after_loading_are_still_checked(self) -> None:
        instance = self._load(_NOT_LISTED_YET)

        with patch.object(config_module, "device_manager", _NOT_LISTED_YET):
            with self.assertRaises(config_module.ConfigValidationError):
                instance.SELECTED_MIC_DEVICE = "Unknown Mic"


if __name__ == "__main__":
    unittest.main()


def test_saved_endpoint_ids_are_preserved_until_devices_are_listed():
    case = SavedDeviceSelectionTests()
    try:
        with patch.dict(_SAVED, {'SELECTED_MIC_DEVICE_ID': 'mic:endpoint-a',
                                'SELECTED_SPEAKER_DEVICE_ID': 'speaker:endpoint-b'}):
            instance = case._load(_NOT_LISTED_YET)
        assert instance.SELECTED_MIC_DEVICE_ID == 'mic:endpoint-a'
        assert instance.SELECTED_SPEAKER_DEVICE_ID == 'speaker:endpoint-b'
    finally:
        case.doCleanups()
