"""TTS owns monitors through drain and timeout callbacks belong to one request."""
from threading import Event, Thread
from time import monotonic

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.audio_routing.monitor_output import MonitorTee
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from models.voice_events import AudioFrame
from test_scheduler import Sink, event, until


class HeldOpener:
    def __init__(self):
        self.entered, self.release = Event(), Event()
        self.sink = Sink()

    def __call__(self, *args, **kwargs):
        self.entered.set()
        assert self.release.wait(5)
        return self.sink


class Provider:
    def __init__(self, url):
        pass

    def synthesize_stream(self, text, voice, language, token, **options):
        yield AudioFrame(b"\x01\x00" * 4800, 48000)


@pytest.fixture
def playback():
    monitors, openers, main = [], [], Sink()

    def monitor_factory(*args, **kwargs):
        opener = HeldOpener()
        monitor = MonitorTee(*args, output_factory=opener, **kwargs)
        openers.append(opener)
        monitors.append(monitor)
        return monitor

    settings = VoiceSettings(mode="original", mic_mode="translated", output_device="cable",
                             monitor="on", monitor_device="speakers")
    bus = VoiceEventBus(settings, provider_factory=Provider, router=AudioRouter(lambda *args: main),
                        monitor_factory=monitor_factory)
    try:
        yield bus, monitors, openers, main
    finally:
        for opener in openers:
            opener.release.set()
        assert bus.close(2)
        assert all(monitor.join(0) for monitor in monitors)


def finish_main(bus, count=1):
    until(lambda: bus.status()["completed"] == count and not bus.status()["active"])


def stop(bus, action):
    if action == "stop":
        bus.cancel()
    elif action == "mute":
        bus.set_muted(True)
    elif action == "disable":
        assert bus.set_enabled(False)
    elif action == "configure":
        bus.configure(bus.settings)
    else:
        # The fake opener cannot exit until the test releases it.
        assert bus.close(timeout=0.05) is False


@pytest.mark.parametrize("action", ["stop", "mute", "disable", "configure", "close"])
def test_stop_cancels_all_monitors_after_main_completion(playback, action):
    bus, monitors, openers, _ = playback
    for index in range(3):
        assert bus.publish(event(str(index)))
        finish_main(bus, index + 1)
        assert openers[index].entered.wait(1)
        assert monitors[index]._queued > 0
    generation = bus.generation()
    stop(bus, action)
    assert bus.generation() == generation + 1
    assert bus.status()["dropped"] == 0
    assert bus.status()["muted"] is (action == "mute")
    assert bus.status()["tts_enabled"] is (action != "disable")
    if action == "disable":
        assert bus.status()["tts_stopping"]
    for monitor, opener in zip(monitors, openers):
        assert monitor._token.is_set()
        assert monitor._queued == 0 and not monitor._queue
        opener.release.set()
        assert monitor.join(1)
        assert opener.sink.data == [] and opener.sink.closed == [False]
    until(lambda: not bus._monitors)
    assert not bus.status()["tts_stopping"]


def test_next_utterance_does_not_wait_and_finished_monitors_are_forgotten(playback):
    bus, monitors, openers, main = playback
    for index in range(2):
        assert bus.publish(event(str(index)))
        finish_main(bus, index + 1)
        assert openers[index].entered.wait(1)
    assert len(main.data) == 20
    assert len(bus._monitors) == 2
    assert all(not monitor.join(0) for monitor in monitors)
    for monitor, opener in zip(monitors, openers):
        opener.release.set()
        assert monitor.join(1)
        assert b"".join(opener.sink.data) == b"\x01\x00" * 4800
        assert opener.sink.closed == [True]
    # No new publish, status query, stop or close is needed to forget them.
    until(lambda: not bus._monitors)


@pytest.mark.parametrize("action", ["stop", "mute", "disable", "configure", "close"])
def test_stop_prevents_more_pcm_from_an_already_playing_monitor(playback, action):
    bus, monitors, openers, _ = playback
    writing, release = Event(), Event()
    try:
        assert bus.publish(event())
        finish_main(bus)
        assert openers[0].entered.wait(1)
        sink = openers[0].sink
        write = sink.write

        def held_write(pcm, token):
            if sink.data:
                writing.set()
                assert release.wait(5)
            write(pcm, token)

        sink.write = held_write
        openers[0].release.set()
        assert writing.wait(1)
        assert len(sink.data) == 1
        stop(bus, action)
        release.set()
        assert monitors[0].join(1)
        assert len(sink.data) == 1 and sink.closed == [False]
        assert monitors[0]._queued == 0
    finally:
        release.set()


def test_close_has_one_bound_and_keeps_ownership_until_monitors_exit(playback):
    bus, monitors, openers, _ = playback
    for index in range(3):
        assert bus.publish(event(str(index)))
        finish_main(bus, index + 1)
        assert openers[index].entered.wait(1)
    started = monotonic()
    assert bus.close(timeout=0.05) is False
    assert monotonic() - started < 0.5
    assert len(bus._monitors) == 3
    assert all(monitor._token.is_set() and not monitor.join(0) for monitor in monitors)
    for opener in openers:
        opener.release.set()
    assert bus.close(timeout=1) is True
    assert not bus._thread.is_alive() and not bus._monitors
    assert all(monitor.join(0) for monitor in monitors)
    assert all(opener.sink.data == [] for opener in openers)


def test_close_waits_for_monitor_device_cleanup(playback):
    bus, monitors, openers, _ = playback
    draining, release, finished = Event(), Event(), Event()
    results = []
    closing = None
    try:
        assert bus.publish(event())
        finish_main(bus)
        assert openers[0].entered.wait(1)

        def close_sink(*, drain, token):
            assert drain
            draining.set()
            assert release.wait(5)

        openers[0].sink.close = close_sink
        openers[0].release.set()
        assert draining.wait(1)

        def close_bus():
            results.append(bus.close(timeout=1))
            finished.set()

        closing = Thread(target=close_bus)
        closing.start()
        until(monitors[0]._token.is_set)
        assert not finished.is_set()
        release.set()
        closing.join(2)
        assert results == [True]
        assert monitors[0].join(0) and not bus._monitors
    finally:
        release.set()
        if closing is not None:
            closing.join(2)


@pytest.mark.parametrize("action", ["stop", "mute", "disable", "configure", "close"])
def test_monitor_created_during_stop_is_owned_and_cancelled(playback, action):
    bus, monitors, openers, main = playback
    entered, release = Event(), Event()
    factory = bus.monitor_factory

    def held_factory(*args, **kwargs):
        monitor = factory(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return monitor

    bus.monitor_factory = held_factory
    try:
        assert bus.publish(event())
        assert entered.wait(1)
        stop(bus, action)
        release.set()
        until(lambda: not bus.status()["active"])
        assert monitors[0].join(1)
        until(lambda: not bus._monitors)
        assert monitors[0]._token.is_set()
        assert main.data == [] and openers[0].sink.data == []
    finally:
        release.set()


def test_source_cancel_only_cancels_that_sources_draining_monitor(playback):
    bus, monitors, openers, _ = playback
    assert bus.publish(event("chat"))
    finish_main(bus)
    assert bus.publish(event("mic", source="mic", translated_text="訳文", target_language="Japanese"))
    finish_main(bus, 2)
    assert all(opener.entered.wait(1) for opener in openers)
    generation = bus.generation()
    bus.cancel_source("mic")
    assert bus.generation() == generation and bus.source_generation("mic") == 1
    assert not monitors[0]._token.is_set() and monitors[1]._token.is_set()
    for monitor, opener in zip(monitors, openers):
        opener.release.set()
        assert monitor.join(1)
    assert openers[0].sink.data and openers[1].sink.data == []


def test_dispatched_stale_timeout_cannot_cancel_the_next_utterance(monkeypatch):
    from models.tts import tts_scheduler

    timers, tokens = [], []
    entered, release = Event(), Event()
    sink = Sink()

    class DispatchedTimer:
        def __init__(self, interval, callback):
            self.callback = callback
            self.cancelled = False

        def start(self):
            timers.append(self)

        def cancel(self):
            self.cancelled = True

    class HeldProvider(Provider):
        def synthesize_stream(self, text, voice, language, token, **options):
            tokens.append(token)
            if len(tokens) == 2:
                entered.set()
                assert release.wait(5)
            token.check()
            yield AudioFrame(b"\x01\x00", 48000)

    monkeypatch.setattr(tts_scheduler, "Timer", DispatchedTimer)
    bus = VoiceEventBus(VoiceSettings(mode="original", output_device="cable"),
                        provider_factory=HeldProvider, router=AudioRouter(lambda *args: sink))
    try:
        assert bus.publish(event("first"))
        finish_main(bus)
        assert timers[0].cancelled
        assert bus.publish(event("second"))
        assert entered.wait(1)
        # Timer.cancel cannot retract a callback already dispatched by Timer.run.
        timers[0].callback()
        assert tokens[0].is_set() and tokens[0].reason == "request_timeout"
        assert not tokens[1].is_set()
        release.set()
        finish_main(bus, 2)
        assert bus.status()["errors"] == 0 and len(sink.data) == 2
    finally:
        release.set()
        assert bus.close()


def test_real_timeout_still_cancels_its_own_utterance():
    tokens, sink = [], Sink()

    class WaitingProvider(Provider):
        def synthesize_stream(self, text, voice, language, token, **options):
            tokens.append(token)
            token.wait(2)
            token.check()
            yield AudioFrame(b"\x01\x00", 48000)

    bus = VoiceEventBus(VoiceSettings(mode="original", output_device="cable"),
                        provider_factory=WaitingProvider, router=AudioRouter(lambda *args: sink),
                        request_timeout=0.05)
    try:
        assert bus.publish(event())
        until(lambda: bus.status()["errors"] == 1)
        assert tokens[0].is_set() and tokens[0].reason == "request_timeout"
        assert bus.status()["last_error"] == "request_timeout" and sink.data == []
    finally:
        assert bus.close()
