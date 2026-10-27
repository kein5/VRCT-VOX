"""Real Main receiver/worker behavior with only application services injected."""
import base64
import importlib.util
import json
from pathlib import Path
from queue import Queue
from threading import Event
from unittest.mock import MagicMock

import pytest

from models.tts.settings import VoiceSettings
from test_controller_integration import controller_module  # noqa: F401


@pytest.fixture
def mainloop_module(controller_module, monkeypatch, tmp_path):  # noqa: F811 (pytest fixture)
    import faulthandler
    import sys
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "controller", controller_module)
    monkeypatch.setattr(faulthandler, "enable", lambda **kwargs: None)
    spec = importlib.util.spec_from_file_location(
        "voice_test_mainloop", Path(__file__).parents[2] / "src-python/mainloop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "printLog", lambda *args: None)
    monkeypatch.setattr(module, "printResponse", lambda *args: None)
    yield module
    module.controller.voice_events.close()
    module._cleanupCrashTraceIfEmpty()


def wire_message(endpoint, data=None):
    encoded = None if data is None else base64.b64encode(json.dumps(data).encode()).decode()
    return json.dumps({"endpoint": endpoint, "data": encoded}) + "\n"


def test_receiver_cancel_bypasses_busy_workers_and_stamps_queued_chat(mainloop_module, monkeypatch):
    module = mainloop_module
    controller = module.controller
    controller.messageFormatter = MagicMock(return_value="text")
    controller.voice_events.configure(VoiceSettings(mode="original", output_device="cable"))
    old_generation = controller.voice_events.generation()
    entered = [Event() for _ in range(3)]
    release, stopped, chat_done = Event(), Event(), Event()
    pending = Queue()

    def busy(index):
        def call(data):
            entered[index].set()
            release.wait(3)
            return {"status": 200, "result": None}
        return call

    def cancel(data):
        result = controller.stopVoice(data)
        stopped.set()
        return result

    def chat(data):
        result = controller.chatMessage(data)
        chat_done.set()
        return result

    mapping = {f"/busy/{i}": {"status": True, "variable": busy(i)} for i in range(3)}
    mapping.update({"/run/stop_voice": {"status": True, "variable": cancel},
                    "/run/send_message_box": {"status": True, "variable": chat}})
    main = module.Main(controller, mapping)
    monkeypatch.setattr(module.sys, "stdin", type("Input", (), {"readline": lambda self: pending.get()})())
    main.startHandler()
    main.startReceiver()
    try:
        for i in range(3):
            pending.put(wire_message(f"/busy/{i}"))
        assert all(e.wait(1) for e in entered)
        pending.put(wire_message("/run/send_message_box", {"id": "queued", "message": "test",
                                                         "_voice_generation": old_generation + 100}))
        pending.put(wire_message("/run/stop_voice"))
        assert stopped.wait(0.25), "stop waited behind occupied ordinary workers"
        assert controller.voice_events.generation() == old_generation + 1
        release.set()
        assert chat_done.wait(1)
        assert controller.voice_events.status()["accepted"] == 0
        module.controller.voice_events.close()
    finally:
        main._stop_event.set()
        release.set()
        pending.put("")
        for thread in main._threads:
            thread.join(2)
