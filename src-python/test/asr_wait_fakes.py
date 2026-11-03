"""ASR wait tests: no devices, inference or services."""

import asyncio
from collections import Counter
from copy import deepcopy
from threading import Event


class CountingConfig:
    def __init__(self):
        self.reads = Counter()
        self.language = "Japanese"

    def __getattr__(self, name):
        self.reads[name] += 1
        if name in ("SELECTED_YOUR_LANGUAGES", "SELECTED_TARGET_LANGUAGES"):
            return deepcopy({"1": {"1": {
                "language": self.language, "country": "Japan", "enable": True,
            }}})
        if name == "SELECTED_TAB_NO":
            return "1"
        if name.endswith("AVG_LOGPROB"):
            return -0.8
        if name.endswith("NO_SPEECH_PROB"):
            return 0.6
        if name.endswith("NO_REPEAT_NGRAM_SIZE"):
            return 0
        raise AttributeError(name)


class FakeRecorder:
    SAMPLE_RATE = 16000
    SAMPLE_WIDTH = 2
    channels = 1

    def __init__(self):
        self.device_error_event = Event()
        self.device_error_info = None

    def recordIntoQueue(self, audio_queue, energy_queue=None):
        self.audio_queue = audio_queue

    def resume(self):
        pass

    def stop(self, **kwargs):
        pass


def run_async(coro):
    return asyncio.run(coro)
