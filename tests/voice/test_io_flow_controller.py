"""The flow panel through the real Controller and TTS scheduler: the route map and stage times (ms)."""
from unittest.mock import MagicMock

from models.audio_routing.audio_router import AudioRouter
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from test_controller_integration import controller_module  # noqa: F401
from test_scheduler import Sink, until


def test_chat_speech_time_reaches_the_message_trace(controller_module, pcm_server):  # noqa: F811
    module = controller_module
    sink = Sink()
    with pcm_server() as (url, _):
        controller = module.Controller()
        sent = []
        controller.run = lambda status, endpoint, payload: sent.append((endpoint, payload))
        controller.messageFormatter = MagicMock(return_value="hello")
        controller.voice_events = VoiceEventBus(VoiceSettings(mode="original", output_device="cable", japanese_url=url),
                                                router=AudioRouter(lambda *args: sink))
        controller.voice_events.on_first_audio = controller._ioSpeechStarted
        try:
            controller.chatMessage({"id": "chat-1", "message": "こんにちは"})
            until(lambda: controller.voice_events.status()["completed"] == 1)
            traces = [payload for endpoint, payload in sent if endpoint == "/run/io_trace"]
            assert traces and all(trace["id"] == "chat-1" and trace["input"] == "chat" for trace in traces)
            final = traces[-1]
            assert final["outputs"]["chatbox"]["state"] == "sent"
            speech = final["outputs"]["speech"]
            assert speech["state"] == "playing" and speech["converted"] is False
            assert isinstance(speech["at_ms"], int) and 0 <= speech["at_ms"] < 10_000
        finally:
            controller.voice_events.close()


def test_io_flow_describes_the_current_settings(controller_module):  # noqa: F811
    module = controller_module
    module.config.ENABLE_TRANSCRIPTION_SEND = False
    module.config.OVERLAY_DESKTOP = True
    controller = module.Controller()
    try:
        result = controller.getIoFlow()
        assert result["status"] == 200
        flow = result["result"]
        voice = {row["id"]: row for row in flow["voice"]["outputs"]}
        chat = {row["id"]: row for row in flow["chat"]["outputs"]}
        assert voice["chatbox"] == {"id": "chatbox", "on": False, "reason": "mic_off"}
        assert chat["chatbox"]["on"] and chat["chatbox"]["content"] == "original"
        assert chat["desktop_caption"]["on"]
        # TTS starts off in the app; the panel says so instead of guessing.
        assert chat["speech"]["reason"] in ("chat_speech_off", "tts_off")
        assert flow["conversion_round_trip_ms"] is None
    finally:
        controller.voice_events.close()
        controller.voice_route.close()
