"""Revocation across translation, rendering and the realtime final queue.

Only delivery workers run: capture, OSC, overlays, logging and audio are fakes.
The real voice bus is used through enqueue; its worker is never started.
"""

import copy
from queue import Empty, Queue
from threading import Event, Lock, Thread
from types import SimpleNamespace
from unittest.mock import Mock
import time

import pytest
from PIL import Image

import controller as module
import model as model_module
from model import Model
from models.message_delivery import ChatboxOrder, DeliveryEpochs
from models.ocr.ocr_pipeline import OcrPipeline
from models.overlay.overlay_image import OverlayImage
from models.transcription.realtime_events import TranscriptUpdate
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from test_controller_message_pipeline import _CONFIG_KEYS, _RUN_MAPPING


class FakeSession:
    def __init__(self, source, options, endpoint):
        self.source = source
        self.namespace = source + "-session"
        self.active = False
        self.updates = Queue()
        self.idle = Event()

    def start(self):
        self.active = True

    def request_stop(self):
        self.active = False

    def close(self, timeout=3):
        self.request_stop()
        return True

    def is_current(self, namespace):
        return self.active and namespace == self.namespace

    def health(self):
        return dict(source=self.source, namespace=self.namespace,
                    state="ready" if self.active else "closed", error_code=None)

    def pop_update(self, timeout):
        try:
            return self.updates.get(timeout=timeout)
        except Empty:
            self.idle.set()
            return None

    def emit(self, item, *, final=True):
        self.idle.clear()
        self.updates.put(TranscriptUpdate(
            self.source, self.namespace, item, 1, item, final,
            "final" if final else "partial", received_ns=time.monotonic_ns()))


def eventually(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.002)


@pytest.fixture
def app(monkeypatch):
    cfg = SimpleNamespace(**{key: copy.deepcopy(getattr(module.config, key)) for key in _CONFIG_KEYS})
    for key in ("ENABLE_TRANSLATION", "ENABLE_TRANSCRIPTION_SEND", "ENABLE_TRANSCRIPTION_RECEIVE",
                "ENABLE_OCR_CAPTURE", "SEND_MESSAGE_TO_VRC", "SEND_RECEIVED_MESSAGE_TO_VRC",
                "OVERLAY_LARGE_LOG", "OVERLAY_SMALL_LOG", "ENABLE_CLIPBOARD", "LOGGER_FEATURE",
                "VRC_MIC_MUTE_SYNC"):
        setattr(cfg, key, True)
    for key in ("SEND_ONLY_TRANSLATED_MESSAGES", "OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES",
                "CONVERT_MESSAGE_TO_HIRAGANA", "CONVERT_MESSAGE_TO_ROMAJI",
                "ENABLE_CHECK_ENERGY_SEND", "ENABLE_CHECK_ENERGY_RECEIVE"):
        setattr(cfg, key, False)
    cfg.SELECTED_TAB_NO = "1"
    cfg.SELECTED_TAB_TARGET_LANGUAGES_NO_LIST = ["1", "2", "3"]
    cfg.SELECTED_YOUR_LANGUAGES = {"1": {"1": {"language": "English", "enable": True}}}
    cfg.SELECTED_TARGET_LANGUAGES = {"1": {
        "1": {"language": "Japanese", "enable": True},
        "2": {"language": "English", "enable": False},
        "3": {"language": "English", "enable": False}}}
    monkeypatch.setattr(module, "config", cfg)
    monkeypatch.setattr(model_module, "config", cfg)

    backend = object.__new__(Model)
    backend.message_delivery = DeliveryEpochs()
    backend.chatbox_order = ChatboxOrder()
    backend.ensure_initialized = Mock()
    backend._mic_session = Mock()
    backend._speaker_session = Mock()
    backend._mic_session.features = {"transcript"}
    backend._speaker_session.features = {"transcript"}
    backend._mic_session.stop_for_handoff.return_value = True
    backend._speaker_session.stop_for_handoff.return_value = True
    backend._ocr_lifecycle_lock = Lock()
    backend._ocr_shutdown_requested = False
    backend.ocr_pipeline = None
    backend.mic_mute_status = False
    backend._mute_status_lock = Lock()
    backend._mute_status_generation = 0
    backend._mute_verification_pending = None
    backend._avatar_query_executor = Mock()
    backend.mic_lifecycle_worker = Mock()
    backend.speaker_lifecycle_worker = Mock()
    backend.mic_mute_status_change_callback = None
    backend.osc_handler = Mock()
    backend.osc_handler.osc_parameter_muteself = "/avatar/parameters/MuteSelf"
    backend.osc_handler.getOSCParameterMuteSelf.return_value = False
    for name in ("checkKeywords", "detectRepeatSendMessage", "detectRepeatReceiveMessage"):
        setattr(backend, name, Mock(return_value=False))
    for name in ("getInputTranslate", "getOutputTranslate"):
        setattr(backend, name, Mock(return_value=(["translation"], [True], ['translated'])))
    for name in ("oscSendMessage", "updateOverlayLargeLog", "updateOverlaySmallLog",
                 "websocketSendMessage", "setCopyToClipboardAndPasteFromClipboard",
                 "addTranslationHistory", "clearRealtimeCaptionOverlay"):
        setattr(backend, name, Mock())
    backend.createOverlayImageLargeLog = Mock(return_value="large")
    backend.createOverlayImageSmallLog = Mock(return_value="small")

    def publish_large(*args, current):
        if current():
            image = backend.createOverlayImageLargeLog(*args)
            if current():
                backend.updateOverlayLargeLog(image)

    backend.publishMessageOverlayLargeLog = Mock(side_effect=publish_large)
    backend.checkWebSocketServerAlive = Mock(return_value=True)
    backend.logger = Mock()
    backend.caption_overlays = []

    def caption_overlay(payload, language, languages, valid, **kwargs):
        if valid():
            backend.caption_overlays.append(payload)

    backend.publishRealtimeCaptionOverlay = Mock(side_effect=caption_overlay)
    monkeypatch.setattr(module, "model", backend)
    monkeypatch.setattr(module, "RealtimeSession", FakeSession)
    monkeypatch.setattr(module.sys, "platform", "linux")
    c = module.Controller.__new__(module.Controller)
    c.run = Mock()
    c.run_mapping = dict(_RUN_MAPPING)
    c._config = cfg
    c._is_overlay_available = lambda: True
    c._realtimeToggles = lambda: False
    c.mic_lifecycle_lock = Lock()
    c.speaker_lifecycle_lock = Lock()
    c._voice_settings_lock = Lock()
    c.voice_events = VoiceEventBus(VoiceSettings(mode="translated", mic_mode="translated"), router=Mock())
    c.voice_events._thread = Mock()  # Exercise real enqueue checks without synthesis/playback.
    c.getVoiceStatus = lambda: {"status": 200, "result": c.voice_events.status()}
    c._initRealtimeASR({"model": "fake", **{
        source: dict(language="en", endpoint=dict(cookie="1", serial="2", name=source, media_class=media))
        for source, media in (("mic", "Audio/Source"), ("speaker", "Audio/Sink"))}})
    backend.startReceiveOSC()  # Registers callbacks on a fake; never opens a socket.
    handlers = backend.osc_handler.setDictFilterAndTarget.call_args.args[0]

    def mute(value=True):
        backend.osc_handler.getOSCParameterMuteSelf.return_value = value
        handlers["/avatar/parameters/MuteSelf"]("/x", value)
        if not value:
            call = backend._avatar_query_executor.submit.call_args
            call.args[0](*call.args[1:])  # Run the authenticated query outside the mute lock.

    subject = SimpleNamespace(c=c, m=backend, cfg=cfg, mute=mute, handlers=handlers)
    yield subject
    assert c._closeRealtimeASR()
    c.voice_events.close()


def start(app, source="mic"):
    c = app.c
    assert c._startRealtime(source, c._realtime_generation[source])["status"] == 200
    c.run.reset_mock()
    return c._realtime_owners[source]


def captions(app):
    return [call.args[2] for call in app.c.run.call_args_list if call.args[1] == "/run/realtime_caption"]


def wait_for_finals(session, delivery):
    # Fence the actual final queue without stopping it: stopping here would
    # hide a missing publication guard by invalidating the session instead.
    assert session.idle.wait(1)
    done = Event()
    update = TranscriptUpdate(session.source, session.namespace, "fence", 1, "", True,
                              "final", received_ns=time.monotonic_ns())
    delivery._finals.put_nowait((update, time.monotonic() + 2, lambda payload: None,
                                lambda event, current: done.set()))
    assert done.wait(1)


def clear_outputs(app):
    for name in ("oscSendMessage", "updateOverlayLargeLog", "updateOverlaySmallLog",
                 "websocketSendMessage", "setCopyToClipboardAndPasteFromClipboard", "addTranslationHistory"):
        getattr(app.m, name).reset_mock()
    app.m.logger.reset_mock()
    app.m.caption_overlays.clear()
    app.c.run.reset_mock()


def assert_no_outputs(app):
    for name in ("oscSendMessage", "updateOverlayLargeLog", "updateOverlaySmallLog",
                 "websocketSendMessage", "setCopyToClipboardAndPasteFromClipboard", "addTranslationHistory"):
        getattr(app.m, name).assert_not_called()
    app.m.logger.info.assert_not_called()
    app.c.run.assert_not_called()
    assert not app.m.caption_overlays
    assert app.c.voice_events.status()["accepted"] == 0


@pytest.mark.parametrize("resume", [False, True])
def test_legacy_mute_during_translation_revokes_every_output(app, resume):
    def translate(*args, **kwargs):
        app.mute()
        # The lifecycle worker has deliberately not run pause/resume.
        app.m._mic_session.pause.assert_not_called()
        if resume:
            app.mute(False)
        return ["translation"], [True], ['translated']

    app.m.getInputTranslate.side_effect = translate
    app.c.micMessage({"text": "old", "language": "English"})
    assert_no_outputs(app)
    if not resume:
        app.mute(False)
    app.m.getInputTranslate.side_effect = None
    app.c.micMessage({"text": "new", "language": "English"})
    app.m.oscSendMessage.assert_called_once()
    app.m.updateOverlayLargeLog.assert_called_once()
    app.m.websocketSendMessage.assert_called_once()
    app.m.logger.info.assert_called_once()
    app.c.run.assert_called_once()


@pytest.mark.parametrize("resume", [False, True])
def test_realtime_mute_during_translation_revokes_every_late_output(app, resume):
    session, delivery = start(app)
    entered, release, finished = Event(), Event(), Event()

    def translate(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return ["translation"], [True], ['translated']

    app.m.getInputTranslate.side_effect = translate
    process = app.c._processMessage

    def observed(*args, **kwargs):
        try:
            return process(*args, **kwargs)
        finally:
            finished.set()

    app.c._processMessage = observed
    try:
        session.emit("old")
        assert entered.wait(1)
        app.mute()
        if resume:
            app.mute(False)
        clear_outputs(app)  # The initial final caption preceded the mute.
        release.set()
        assert finished.wait(1)
        wait_for_finals(session, delivery)
        assert_no_outputs(app)
    finally:
        release.set()


@pytest.mark.parametrize("source", ["mic", "speaker"])
def test_realtime_muted_captions_and_new_results_after_unmute(app, source):
    session, delivery = start(app, source)
    app.mute()
    session.emit("muted-partial", final=False)
    session.emit("muted-final")
    eventually(lambda: "muted-final" in delivery._terminal)
    if source == "speaker":
        eventually(lambda: any(p["state"] == "translated" for p in captions(app)))
        assert app.m.caption_overlays
        app.m.websocketSendMessage.assert_called_once()
        app.m.logger.info.assert_called_once()
    else:
        assert_no_outputs(app)
    app.mute(False)
    session.emit("new")
    eventually(lambda: any(p["item_id"] == "new" and p["state"] == "translated" for p in captions(app)))
    if source == "mic":
        assert app.c.voice_events.status()["accepted"] == 1
        app.m.oscSendMessage.assert_called_once()
    else:
        app.m.oscSendMessage.assert_not_called()
        assert app.c.voice_events.status()["accepted"] == 0


@pytest.mark.parametrize("source", ["speaker", "chat"])
def test_mic_mute_does_not_revoke_other_sources(app, source):
    def translate(*args, **kwargs):
        app.mute()
        return ["translation"], [True], ['translated']

    if source == "speaker":
        app.m.getOutputTranslate.side_effect = translate
        app.c.speakerMessage({"text": "received", "language": "English"})
        app.m.updateOverlaySmallLog.assert_called_once()
        app.c.run.assert_called_once()
    else:
        app.m.getInputTranslate.side_effect = translate
        result = app.c.chatMessage({"id": "quick-chat", "message": "typed"})
        assert result["result"]["translations"][0]["message"] == "translation"
        assert app.c.voice_events.status()["accepted"] == 1
    app.m.oscSendMessage.assert_called_once()
    app.m.updateOverlayLargeLog.assert_called_once()
    app.m.websocketSendMessage.assert_called_once()
    app.m.logger.info.assert_called_once()


@pytest.mark.parametrize("cycle", ["stop_voice", "mute_resume", "tts_off_on"])
def test_queued_realtime_final_keeps_admission_voice_generation(app, cycle):
    session, delivery = start(app)
    entered, release = Event(), Event()

    def translate(message, **kwargs):
        if message == "first":
            entered.set()
            assert release.wait(2)
        return ["translation"], [True], ['translated']

    app.m.getInputTranslate.side_effect = translate
    try:
        session.emit("first")
        assert entered.wait(1)
        session.emit("queued")
        eventually(lambda: delivery._finals.qsize() == 1)
        if cycle == "stop_voice":
            assert app.c.stopVoice()["status"] == 200
        elif cycle == "mute_resume":
            app.c.voice_events.set_muted(True)
            app.c.voice_events.set_muted(False)
        else:
            assert app.c.voice_events.set_enabled(False)
            assert app.c.voice_events.set_enabled(True)
        release.set()
        eventually(lambda: any(p["item_id"] == "queued" and p["state"] == "translated" for p in captions(app)))
        assert app.m.oscSendMessage.call_count == 2
        assert app.m.websocketSendMessage.call_count == 2
        assert app.m.logger.info.call_count == 2
        assert app.c.voice_events.status()["accepted"] == 0
        session.emit("after-cycle")
        eventually(lambda: any(p["item_id"] == "after-cycle" and p["state"] == "translated" for p in captions(app)))
        assert app.c.voice_events.status()["accepted"] == 1
    finally:
        release.set()


@pytest.mark.parametrize("source", ["mic", "speaker", "ocr"])
@pytest.mark.parametrize("only_translated", [False, True])
def test_disable_during_slow_render_revokes_before_bounded_cleanup(app, source, only_translated):
    app.cfg.OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES = only_translated
    entered, release = Event(), Event()
    errors = []
    renderer = app.m.createOverlayImageSmallLog if source == "speaker" else app.m.createOverlayImageLargeLog

    def render(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return "late-image"

    renderer.side_effect = render
    if source == "ocr":
        pipeline = OcrPipeline(callback=app.c.ocrMessage)
        pipeline._thread = Mock()
        pipeline._thread.is_alive.return_value = True
        app.m.ocr_pipeline = pipeline
        cleanup = pipeline._thread.join
        stop = app.c.setDisableOcrCapture
        feature = "ENABLE_OCR_CAPTURE"
    else:
        cleanup = getattr(app.m, "_" + source + "_session").reconfigure
        stop = app.c.setDisableTranscriptionSend if source == "mic" else app.c.setDisableTranscriptionReceive
        feature = "ENABLE_TRANSCRIPTION_SEND" if source == "mic" else "ENABLE_TRANSCRIPTION_RECEIVE"
    admitted = app.c._messagePublicationGuard(source)
    cleanup.side_effect = lambda *a, **kw: pytest.fail("delivery not revoked before join") if admitted() else None

    def deliver():
        try:
            getattr(app.c, source + "Message")({"text": "old", "language": "English"})
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=deliver)
    worker.start()
    try:
        assert entered.wait(1)
        assert stop() == {"status": 200, "result": False}
        cleanup.assert_called_once()
        if source == "ocr":
            cleanup.assert_called_once_with(timeout=5.0)
        clear_outputs(app)  # Legacy OSC may already have been published before render.
        # Re-enabling the feature cannot rescue an old render.
        setattr(app.cfg, feature, True)
        release.set()
        worker.join(2)
        assert not worker.is_alive() and not errors
        assert_no_outputs(app)
        renderer.side_effect = None
        getattr(app.c, source + "Message")({"text": "new", "language": "English"})
        app.m.updateOverlayLargeLog.assert_called_once()
        app.m.websocketSendMessage.assert_called_once()
        app.m.logger.info.assert_called_once()
    finally:
        release.set()
        worker.join(2)


@pytest.mark.parametrize("source", ["mic", "speaker", "ocr"])
def test_disable_during_translation_drops_all_outputs_but_keeps_typed_chat(app, source):
    stop = {"mic": app.c.setDisableTranscriptionSend, "speaker": app.c.setDisableTranscriptionReceive,
            "ocr": app.c.setDisableOcrCapture}[source]
    translator = app.m.getInputTranslate if source == "mic" else app.m.getOutputTranslate

    def translate(*args, **kwargs):
        stop()
        return ["translation"], [True], ['translated']

    translator.side_effect = translate
    getattr(app.c, source + "Message")({"text": "old", "language": "English"})
    assert_no_outputs(app)
    translator.side_effect = None
    result = app.c.chatMessage({"id": "typed", "message": "still works"})
    assert result["status"] == 200
    app.m.oscSendMessage.assert_called_once()
    app.m.websocketSendMessage.assert_called_once()
    assert app.c.voice_events.status()["accepted"] == 1


@pytest.mark.parametrize("boundary", ["osc", "large_overlay", "clipboard", "ui", "websocket", "logger", "history"])
def test_every_legacy_publication_rechecks_epoch(app, boundary):
    sinks = [app.m.oscSendMessage, app.m.updateOverlayLargeLog,
             app.m.setCopyToClipboardAndPasteFromClipboard, app.c.run,
             app.m.websocketSendMessage, app.m.logger.info, app.m.addTranslationHistory]
    index = ["osc", "large_overlay", "clipboard", "ui", "websocket", "logger", "history"].index(boundary)
    sinks[index].side_effect = lambda *args, **kwargs: app.mute()
    app.c.micMessage({"text": "old", "language": "English"})
    for sink in sinks[:index + 1]:
        sink.assert_called_once()
    for sink in sinks[index + 1:]:
        sink.assert_not_called()


@pytest.mark.parametrize("via", ["osc", "avatar", "initial_query"])
def test_mute_epoch_changes_before_deferred_pause(app, via):
    mic = app.c._messagePublicationGuard("mic")
    speaker = app.c._messagePublicationGuard("speaker")
    if via == "osc":
        app.mute()
    elif via == "avatar":
        app.m.osc_handler.getOSCParameterMuteSelf.return_value = True
        app.handlers["/avatar/change"]("/avatar/change", "avatar")
        call = app.m._avatar_query_executor.submit.call_args
        call.args[0](*call.args[1:])
    else:
        app.m.osc_handler.getOSCParameterMuteSelf.return_value = True
        app.m.setMuteSelfStatus()
    app.mute(False)
    assert not mic() and speaker()
    app.m._mic_session.pause.assert_not_called()


def test_queued_finals_before_and_during_vrc_mute_stay_revoked_after_unmute(app):
    session, delivery = start(app)
    entered, release = Event(), Event()

    def translate(message, **kwargs):
        if message == "translating":
            entered.set()
            assert release.wait(2)
        return ["translation"], [True], ['translated']

    app.m.getInputTranslate.side_effect = translate
    try:
        session.emit("translating")
        assert entered.wait(1)
        session.emit("queued-before-mute")
        eventually(lambda: delivery._finals.qsize() == 1)
        app.mute()
        clear_outputs(app)
        session.emit("queued-while-muted")
        eventually(lambda: delivery._finals.qsize() == 2)
        assert_no_outputs(app)
        app.mute(False)
        release.set()
        session.emit("new")
        eventually(lambda: any(p["item_id"] == "new" and p["state"] == "translated" for p in captions(app)))
        assert [call.args[0] for call in app.m.getInputTranslate.call_args_list] == ["translating", "new"]
        assert all(p["item_id"] == "new" for p in captions(app))
        assert all(p["item_id"] == "new" for p in app.m.caption_overlays)
        app.m.oscSendMessage.assert_called_once()
        app.m.websocketSendMessage.assert_called_once()
        app.m.logger.info.assert_called_once()
        assert app.c.voice_events.status()["accepted"] == 1
    finally:
        release.set()


@pytest.mark.parametrize("final", [False, True])
def test_realtime_caption_render_rechecks_mute_epoch(app, final):
    session, delivery = start(app)
    rendered = Event()

    def render(payload, language, languages, valid, **kwargs):
        app.mute()
        app.mute(False)
        if valid():
            app.m.caption_overlays.append(payload)
        rendered.set()

    app.m.publishRealtimeCaptionOverlay.side_effect = render
    session.emit("old", final=final)
    assert rendered.wait(1)
    wait_for_finals(session, delivery)
    assert not app.m.caption_overlays
    app.m.oscSendMessage.assert_not_called()
    app.m.websocketSendMessage.assert_not_called()
    app.m.logger.info.assert_not_called()
    assert app.c.voice_events.status()["accepted"] == 0
    assert not any(p["state"] == "translated" for p in captions(app))


def test_realtime_mute_at_history_blocks_tts_and_translated_caption(app):
    session, delivery = start(app)
    processed = Event()

    def revoke(*args):
        app.mute()
        app.mute(False)
        processed.set()

    app.m.addTranslationHistory.side_effect = revoke
    session.emit("old")
    assert processed.wait(1)
    wait_for_finals(session, delivery)
    # Text sinks before history already ran; later enqueue and caption must recheck.
    app.m.oscSendMessage.assert_called_once()
    app.m.websocketSendMessage.assert_called_once()
    app.m.logger.info.assert_called_once()
    assert app.c.voice_events.status()["accepted"] == 0
    assert not any(p["state"] == "translated" for p in captions(app))


def test_vrc_mute_sync_off_leaves_mic_delivery_unchanged(app):
    app.cfg.VRC_MIC_MUTE_SYNC = False
    app.m.mic_mute_status = True
    app.c.micMessage({"text": "allowed", "language": "English"})
    app.m.oscSendMessage.assert_called_once()
    app.m.websocketSendMessage.assert_called_once()
    app.m.logger.info.assert_called_once()
    app.c.run.assert_called_once()


@pytest.mark.parametrize("source", ["mic", "speaker", "ocr"])
def test_callback_admission_is_not_restamped_after_disable_enable(app, source):
    stop = {"mic": app.c.setDisableTranscriptionSend, "speaker": app.c.setDisableTranscriptionReceive,
            "ocr": app.c.setDisableOcrCapture}[source]
    feature = {"mic": "ENABLE_TRANSCRIPTION_SEND", "speaker": "ENABLE_TRANSCRIPTION_RECEIVE",
               "ocr": "ENABLE_OCR_CAPTURE"}[source]

    class Result(dict):
        def __getitem__(self, key):
            if key == "text":
                stop()
                setattr(app.cfg, feature, True)
            return super().__getitem__(key)

        def get(self, key, default=None):
            return self[key] if key in self else default

    getattr(app.c, source + "Message")(Result(text="old", language="English"))
    assert_no_outputs(app)


@pytest.mark.parametrize("source", ["mic", "speaker", "ocr"])
def test_revoked_large_overlay_history_cannot_leak_in_a_later_typed_render(app, source):
    # Exercise the actual Model transaction and OverlayImage history, not the
    # fixture's fake renderer. No fonts, GUI or OpenVR destination is opened.
    app.m.overlay_image = OverlayImage()
    app.m.overlay = Mock()
    for name in ("createOverlayImageLargeLog", "updateOverlayLargeLog", "publishMessageOverlayLargeLog"):
        setattr(app.m, name, getattr(Model, name).__get__(app.m))
    app.m.overlay_image.createTextboxLargeLog = lambda *a, **kw: Image.new("RGBA", (100, 20), "white")
    app.m.publishMessageOverlayLargeLog("send", "published", "English", [], {}, [], [], current=lambda: True)
    app.m.overlay.updateImage.reset_mock()
    stop = {"mic": app.c.setDisableTranscriptionSend, "speaker": app.c.setDisableTranscriptionReceive,
            "ocr": app.c.setDisableOcrCapture}[source]

    def revoke_render(kind, message, *args, **kwargs):
        if message == "revoked":
            stop()
        return Image.new("RGBA", (100, 20), "white")

    app.m.overlay_image.createTextboxLargeLog = revoke_render
    getattr(app.c, source + "Message")({"text": "revoked", "language": "English"})
    app.m.overlay.updateImage.assert_not_called()
    assert [row["message"] for row in app.m.overlay_image.message_log] == ["published"]
    drawn = []

    def render(kind, message, *args, **kwargs):
        drawn.append(message)
        return Image.new("RGBA", (100, 20), "white")

    app.m.overlay_image.createTextboxLargeLog = render
    app.c.chatMessage({"id": "new-typed", "message": "new"})
    app.m.overlay.updateImage.assert_called_once()
    assert drawn == ["published", "new"]


@pytest.mark.parametrize("source", ["mic", "speaker"])
@pytest.mark.parametrize("pause", ["device_update", "settings", "handoff"])
def test_internal_pause_preserves_inflight_legacy_delivery(app, monkeypatch, source, pause):
    title = "Mic" if source == "mic" else "Speaker"
    direction = "Send" if source == "mic" else "Receive"
    feature = "ENABLE_TRANSCRIPTION_" + direction.upper()
    translator = app.m.getInputTranslate if source == "mic" else app.m.getOutputTranslate
    epoch = app.m.message_delivery.snapshot(source)
    manager = Mock()
    monkeypatch.setattr(module, "device_manager", manager)
    worker = getattr(app.m, source + "_lifecycle_worker")
    # Execute the production before/after callbacks through a fake FIFO worker.
    worker.enqueue.side_effect = lambda fn, **kwargs: fn()

    def translate(*args, **kwargs):
        if pause == "device_update":
            getattr(app.c, "applyAuto" + title + "Select")()
            getattr(manager, "setCallbackProcessBeforeUpdate" + title + "Devices").call_args.args[0]()
            getattr(manager, "setCallbackProcessAfterUpdate" + title + "Devices").call_args.args[0]()
            assert getattr(app.cfg, feature) is True
        elif pause == "settings":
            # ConfigPageCloseTriggerController uses the same endpoint with
            # explicit pause intent, and restores ON when Settings closes.
            getattr(app.c, "setDisableTranscription" + direction)({"reason": "settings_pause"})
            assert getattr(app.cfg, feature) is False
        else:
            start(app, source)
            assert getattr(app.cfg, feature) is False
        assert app.m.message_delivery.current(source, epoch)
        return ["translation"], [True], ['translated']

    translator.side_effect = translate
    getattr(app.c, source + "Message")({"text": "already spoken", "language": "English"})
    app.m.oscSendMessage.assert_called_once()
    app.m.updateOverlayLargeLog.assert_called_once()
    app.m.websocketSendMessage.assert_called_once()
    app.m.logger.info.assert_called_once()
    app.m.addTranslationHistory.assert_called_once()
    app.c.run.assert_called_once()
    if pause == "settings":
        assert getattr(app.c, "setEnableTranscription" + direction)()["result"] is True


@pytest.mark.parametrize("source", ["mic", "speaker"])
def test_user_off_while_settings_paused_revokes_inflight_delivery(app, source):
    disable = app.c.setDisableTranscriptionSend if source == "mic" else app.c.setDisableTranscriptionReceive
    translator = app.m.getInputTranslate if source == "mic" else app.m.getOutputTranslate

    def translate(*args, **kwargs):
        disable({"reason": "settings_pause"})
        disable()  # Already paused, but explicit OFF still revokes admitted work.
        return ["translation"], [True], ['translated']

    translator.side_effect = translate
    getattr(app.c, source + "Message")({"text": "old", "language": "English"})
    assert_no_outputs(app)


@pytest.mark.parametrize("source", ["mic", "speaker"])
@pytest.mark.parametrize("reason", ["device_loss", "pipeline_error", "vram", "start_error", "start_refused"])
def test_error_disable_revokes_before_cleanup(app, monkeypatch, source, reason):
    direction = "Send" if source == "mic" else "Receive"
    title = "Mic" if source == "mic" else "Speaker"
    current = app.c._messagePublicationGuard(source)
    translator = app.m.getInputTranslate if source == "mic" else app.m.getOutputTranslate
    session = getattr(app.m, "_" + source + "_session")
    monkeypatch.setattr(module, "errorLogging", Mock())
    app.c.run_mapping["error_transcription_" + source + "_vram_overflow"] = "/run/vram"

    def cleanup(**kwargs):
        if kwargs.get("transcript") is False:
            assert not current()

    session.reconfigure.side_effect = cleanup
    worker = getattr(app.m, source + "_lifecycle_worker")

    def enqueue(fn, **kwargs):
        assert not current()
        fn()

    worker.enqueue.side_effect = enqueue

    def translate(*args, **kwargs):
        if reason == "device_loss":
            app.c._disableAudioAfterDeviceLoss(source)
            worker.enqueue.assert_called_once()
        elif reason == "pipeline_error":
            app.c._disableTranscriptionAfterPipelineError(source)
        else:
            start_capture = Mock(return_value=False)
            if reason != "start_refused":
                start_capture.side_effect = ValueError("VRAM_OUT_OF_MEMORY") if reason == "vram" else RuntimeError("failed")
            monkeypatch.setattr(app.m, "start" + title + "Transcript", start_capture)
            assert getattr(app.c, "startTranscription" + direction + "Message")() is False
        assert not current()
        assert getattr(app.cfg, "ENABLE_TRANSCRIPTION_" + direction.upper()) is False
        app.c.run.reset_mock()  # Error/disable notifications are expected.
        return ["translation"], [True], ['translated']

    translator.side_effect = translate
    getattr(app.c, source + "Message")({"text": "old", "language": "English"})
    assert_no_outputs(app)


@pytest.mark.parametrize("source", ["mic", "speaker"])
def test_device_loss_of_energy_meter_alone_does_not_revoke_delivery(app, source):
    direction = "SEND" if source == "mic" else "RECEIVE"
    setattr(app.cfg, "ENABLE_TRANSCRIPTION_" + direction, False)
    setattr(app.cfg, "ENABLE_CHECK_ENERGY_" + direction, True)
    current = app.c._messagePublicationGuard(source)
    worker = getattr(app.m, source + "_lifecycle_worker")
    worker.enqueue.side_effect = lambda fn, **kwargs: fn()
    app.c._disableAudioAfterDeviceLoss(source)
    assert current()


@pytest.mark.parametrize("source", ["mic", "speaker"])
def test_realtime_toggle_off_revokes_source_but_settings_pause_keeps_epoch(app, source):
    app.c._realtimeToggles = lambda: True
    current = app.c._messagePublicationGuard(source)
    disable = app.c.setDisableTranscriptionSend if source == "mic" else app.c.setDisableTranscriptionReceive
    disable({"reason": "settings_pause"})
    assert current()
    disable()
    assert not current()


def test_low_level_ocr_stop_is_not_disable_intent(app):
    current = app.c._messagePublicationGuard("ocr")
    app.m.stopOCRCapture()
    assert current()


@pytest.mark.parametrize("source", ["mic", "speaker"])
def test_failed_realtime_handoff_revokes_legacy_delivery(app, source):
    current = app.c._messagePublicationGuard(source)
    getattr(app.m, "_" + source + "_session").stop_for_handoff.return_value = False
    result = app.c._startRealtime(source, app.c._realtime_generation[source])
    assert result["result"]["error_code"] == "realtime_legacy_stop_failed"
    assert not current()


@pytest.mark.parametrize("source", ["mic", "speaker"])
def test_terminal_realtime_failure_only_revokes_its_current_owner(app, source):
    app.c._realtimeToggles = lambda: True
    app.c._publishRealtimeToggle = Mock()
    app.c._realtime_requested[source] = True
    generation = app.c._realtime_generation[source]
    current = app.c._messagePublicationGuard(source)
    app.c._realtimeEnded(source, generation)
    assert not current()
    current = app.c._messagePublicationGuard(source)
    app.c._realtime_generation[source] += 1
    app.c._realtimeEnded(source, generation)
    assert current()


def test_shutdown_revokes_all_sources_before_any_cleanup_wait(app):
    guards = [app.c._messagePublicationGuard(source) for source in ("mic", "speaker", "ocr", "chat")]

    class CleanupReached(Exception):
        pass

    def cleanup(*args):
        assert not any(current() for current in guards)
        raise CleanupReached

    app.c._stopServiceForShutdown = cleanup
    with pytest.raises(CleanupReached):
        app.c.shutdown()
