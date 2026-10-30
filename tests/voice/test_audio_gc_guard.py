import gc
import pytest
from models.audio_routing.audio_router import AudioRouter
from models.tts.speechcpp_tts import CancelToken
from models.voice_events import AudioFrame


def test_playback_defers_automatic_gc_through_drain_and_restores_on_error():
    initial = gc.isenabled()
    gc.enable()

    class Sink:
        def write(self, pcm, token):
            assert not gc.isenabled()

        def close(self, **kwargs):
            assert not gc.isenabled()
            raise RuntimeError("drain-failed")

    try:
        router = AudioRouter(lambda *args: Sink())
        with pytest.raises(RuntimeError, match="drain-failed"):
            router.play(
                [AudioFrame(b"\1\0" * 480, 48000)],
                "test",
                CancelToken(),
                lambda *args: None,
            )
        assert gc.isenabled()
    finally:
        gc.enable() if initial else gc.disable()


def test_nested_users_and_preexisting_disabled_state_are_preserved():
    from models.audio_routing.gc_guard import defer_cyclic_gc

    initial = gc.isenabled()
    try:
        for enabled in (True, False):
            gc.enable() if enabled else gc.disable()
            with defer_cyclic_gc():
                assert not gc.isenabled()
                with defer_cyclic_gc():
                    assert not gc.isenabled()
                assert not gc.isenabled()
            assert gc.isenabled() == enabled
    finally:
        gc.enable() if initial else gc.disable()


def test_overlapping_threads_restore_only_after_last_writer():
    from threading import Event, Thread
    from models.audio_routing.gc_guard import defer_cyclic_gc

    initial = gc.isenabled()
    gc.enable()
    started = [Event(), Event()]
    release = [Event(), Event()]

    def writer(i):
        with defer_cyclic_gc():
            started[i].set()
            release[i].wait(2)

    threads = [Thread(target=writer, args=(i,)) for i in range(2)]
    try:
        for thread in threads:
            thread.start()
        assert all(event.wait(1) for event in started)
        release[0].set()
        threads[0].join(1)
        assert not threads[0].is_alive() and not gc.isenabled()
        release[1].set()
        threads[1].join(1)
        assert not threads[1].is_alive() and gc.isenabled()
    finally:
        for event in release:
            event.set()
        for thread in threads:
            thread.join(2)
        gc.enable() if initial else gc.disable()
