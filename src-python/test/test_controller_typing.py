"""Exercise production typing endpoints with an in-memory OSC sink; no runtime startup."""
import ast
from pathlib import Path
from threading import Event, RLock, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def typing():
    source = Path(__file__).resolve().parents[1] / "controller.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    controller = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Controller")
    methods = {"typingMessageBox", "stopTypingMessageBox", "setEnableSendMessageToVrc", "setDisableSendMessageToVrc"}
    controller.body = [node for node in controller.body
                       if isinstance(node, ast.FunctionDef) and node.name in methods
                       or isinstance(node, ast.Assign) and any(
                           isinstance(target, ast.Name) and target.id in {"_typing_lock", "_typing_active"}
                           for target in node.targets)]
    config = SimpleNamespace(SEND_MESSAGE_TO_VRC=True)
    sent = []
    model = SimpleNamespace(oscStartSendTyping=Mock(side_effect=lambda: sent.append(True)),
                            oscStopSendTyping=Mock(side_effect=lambda: sent.append(False)))
    namespace = {"config": config, "model": model, "RLock": RLock}
    exec(compile(ast.Module(body=[controller], type_ignores=[]), str(source), "exec"), namespace)
    return SimpleNamespace(controller=namespace["Controller"], config=config, model=model, sent=sent)


def test_start_and_stop_preserve_endpoint_responses(typing):
    assert typing.controller.typingMessageBox() == {"status": 200, "result": True}
    assert typing.controller.stopTypingMessageBox() == {"status": 200, "result": True}
    typing.controller.stopTypingMessageBox()
    assert typing.sent == [True, False]


def test_disabled_sending_never_starts_or_resets_an_unowned_indicator(typing):
    typing.config.SEND_MESSAGE_TO_VRC = False
    typing.controller.typingMessageBox()
    typing.controller.stopTypingMessageBox()
    typing.controller.setDisableSendMessageToVrc()
    assert typing.sent == []


def test_stop_resets_owned_indicator_even_if_sending_was_disabled_since(typing):
    typing.controller.typingMessageBox()
    typing.config.SEND_MESSAGE_TO_VRC = False
    typing.controller.stopTypingMessageBox()
    typing.controller.typingMessageBox()
    typing.controller.stopTypingMessageBox()
    assert typing.sent == [True, False]


def test_disable_resets_without_waiting_for_blur_or_clear(typing):
    typing.controller.typingMessageBox()
    assert typing.controller.setDisableSendMessageToVrc() == {"status": 200, "result": False}
    typing.controller.typingMessageBox()
    typing.controller.setDisableSendMessageToVrc()
    assert typing.sent == [True, False]
    assert typing.controller.setEnableSendMessageToVrc() == {"status": 200, "result": True}
    assert typing.sent == [True, False]  # Enabling output alone never starts typing.
    typing.controller.typingMessageBox()
    typing.controller.stopTypingMessageBox()
    assert typing.sent == [True, False, True, False]


def test_failed_reset_remains_owned_and_can_be_reset_while_disabled(typing):
    typing.controller.typingMessageBox()
    typing.model.oscStopSendTyping.side_effect = OSError("send failed")
    with pytest.raises(OSError, match="send failed"):
        typing.controller.setDisableSendMessageToVrc()
    assert typing.config.SEND_MESSAGE_TO_VRC is False
    typing.controller.typingMessageBox()
    typing.model.oscStopSendTyping.side_effect = lambda: typing.sent.append(False)
    typing.controller.stopTypingMessageBox()
    assert typing.sent == [True, False]


def test_disable_serializes_with_an_inflight_start(typing):
    started, release, disabling, disabled = Event(), Event(), Event(), Event()
    errors = []

    def start():
        started.set()
        if not release.wait(2):
            raise TimeoutError("start was not released")
        typing.sent.append(True)

    def run(callback):
        try:
            callback()
        except Exception as error:
            errors.append(error)

    def disable():
        disabling.set()
        typing.controller.setDisableSendMessageToVrc()
        disabled.set()

    typing.model.oscStartSendTyping.side_effect = start
    starter = Thread(target=run, args=(typing.controller.typingMessageBox,), daemon=True)
    disabler = Thread(target=run, args=(disable,), daemon=True)
    starter.start()
    try:
        assert started.wait(1)
        disabler.start()
        assert disabling.wait(1)
        assert not disabled.wait(0.05)
        assert typing.config.SEND_MESSAGE_TO_VRC is True
    finally:
        release.set()
        starter.join(2)
        if disabler.ident is not None:
            disabler.join(2)
    assert not starter.is_alive() and not disabler.is_alive()
    assert errors == []
    assert disabled.is_set()
    typing.controller.typingMessageBox()
    assert typing.sent == [True, False]
