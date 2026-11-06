"""入力・期限・停止による文字起こしの起床。音声と推論は fake のみ。"""

from datetime import datetime, timedelta
from queue import Queue
from statistics import median
from threading import Event, Thread
from time import perf_counter, sleep
import unittest
from unittest.mock import Mock, patch

import model as model_module
from model import MicSession, SpeakerSession, _AudioQueue
from models.transcription.transcription_recorder import BaseEnergyAndAudioRecorder, BaseVadAndAudioRecorder
from models.transcription.transcription_transcriber import AudioTranscriber
from utils import putDroppingOldestOnFull
from asr_wait_fakes import CountingConfig, FakeRecorder


class ObservedQueue(_AudioQueue):
    def __init__(self):
        super().__init__()
        self.waits = Queue()

    def waitForWork(self, timeout):
        self.waits.put(timeout)
        return super().waitForWork(timeout)


class TestTranscriptionWait(unittest.TestCase):
    def setUp(self):
        self.config = CountingConfig()
        self.enterContext(patch.object(model_module, "config", self.config))
        self.enterContext(patch.object(model_module, "_AudioQueue", ObservedQueue))
        self.enterContext(patch("models.transcription.transcription_transcriber.printLog"))

    def start(self, session_cls=MicSession, *, vad=False, timeout=3, finalize=None):
        recorder = FakeRecorder()
        transcriber = AudioTranscriber(
            session_cls is SpeakerSession, recorder, timeout, 10, "Google",
            vad_segmented=vad,
        )
        transcriber._finalizeAndTranscribe = Mock(side_effect=finalize, return_value=True)
        session = session_cls()
        session.features = {"transcript"}
        session._transcribe = Mock(wraps=session._transcribe)
        with patch.object(session, "_create_recorder", return_value=recorder), patch.object(
            session, "_create_transcriber", return_value=transcriber,
        ):
            session._start(device={"name": "fake", "index": 0})
        self.addCleanup(session._stop)
        self.assertIsNone(recorder.audio_queue.waits.get(timeout=1))
        return session, transcriber, recorder.audio_queue

    def test_idle_has_no_rounds_or_config_reads_for_one_second(self):
        sessions = [self.start(cls) for cls in (MicSession, SpeakerSession)]
        sleep(1)
        for session, transcriber, queue in sessions:
            self.assertEqual(session._transcribe.call_count, 0)
            self.assertTrue(queue.waits.empty())
            transcriber._finalizeAndTranscribe.assert_not_called()
            worker = session._print_transcript
            started = perf_counter()
            self.assertFalse(session._stop())
            self.assertLess(perf_counter() - started, 0.5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sum(self.config.reads.values()), 0)

    def test_chunk_wakes_promptly_and_reads_current_language_once_per_round(self):
        for cls in (MicSession, SpeakerSession):
            with self.subTest(source=cls.__name__):
                processed = Queue()
                session, transcriber, queue = self.start(
                    cls, vad=True, finalize=lambda *args: processed.put((perf_counter(), args)) or True,
                )
                self.config.reads.clear()
                self.config.language = "English"
                latencies = []
                for _ in range(30):
                    started = perf_counter()
                    queue.put((b"\1\0" * 160, datetime.now(), "silence"))
                    finished, args = processed.get(timeout=1)
                    latencies.append(finished - started)
                    self.assertEqual(args[:2], (["English"], ["Japan"]))
                    self.assertIsNone(queue.waits.get(timeout=1))
                key = "SELECTED_YOUR_LANGUAGES" if cls is MicSession else "SELECTED_TARGET_LANGUAGES"
                self.assertEqual(self.config.reads[key], 30)
                self.assertEqual(sum(self.config.reads.values()), 150)
                self.assertLess(median(latencies), 0.25)
                print(f"{cls.__name__}: enqueue-to-finalize median_ms={median(latencies) * 1000:.3f}, n=30")
                session._stop()

    def test_phrase_deadline_resets_without_resending_and_then_waits_indefinitely(self):
        session, transcriber, queue = self.start(timeout=0.2)
        spoken = datetime.now()
        queue.put((b"\1\0" * 160, spoken))
        remaining = queue.waits.get(timeout=1)
        self.assertGreater(remaining, 0)
        # Wall-clock arithmetic can overshoot by a microsecond (seen on Windows: 0.200001)
        self.assertLessEqual(remaining, 0.2 + 1e-3)
        self.assertTrue(transcriber.audio_sources["last_sample"])
        self.assertIsNone(queue.waits.get(timeout=1))
        elapsed = (datetime.now() - spoken).total_seconds()
        self.assertGreaterEqual(elapsed, 0.2)
        self.assertLess(elapsed, 0.7)
        self.assertEqual(transcriber.audio_sources["last_sample"], b"")
        self.assertIsNone(transcriber.audio_sources["phrase_started_at"])
        transcriber._finalizeAndTranscribe.assert_called_once()
        self.assertEqual(session._transcribe.call_count, 2)
        self.assertEqual(self.config.reads["SELECTED_YOUR_LANGUAGES"], 2)
        sleep(0.1)
        self.assertTrue(queue.waits.empty())

    def test_new_chunk_rearms_deadline_and_vad_has_no_wall_clock_deadline(self):
        session, transcriber, queue = self.start(timeout=0.15)
        queue.put((b"\1\0", datetime.now()))
        self.assertIsNotNone(queue.waits.get(timeout=1))
        sleep(0.08)
        spoken = datetime.now()
        queue.put((b"\2\0", spoken))
        self.assertIsNotNone(queue.waits.get(timeout=1))
        self.assertIsNone(queue.waits.get(timeout=1))
        self.assertGreaterEqual((datetime.now() - spoken).total_seconds(), 0.15)
        self.assertEqual(transcriber._finalizeAndTranscribe.call_count, 2)
        session._stop()
        session, transcriber, queue = self.start(vad=True, timeout=0.02)
        queue.put((b"\1\0", datetime.now(), "max_duration"))
        self.assertIsNone(queue.waits.get(timeout=1))
        sleep(0.05)
        self.assertTrue(queue.waits.empty())
        self.assertTrue(transcriber.audio_sources["last_sample"])

    def test_stop_during_processing_with_full_queue_cannot_lose_stop(self):
        entered, release, stopped = Event(), Event(), Event()

        def finalize(*args):
            entered.set()
            release.wait(2)
            return True

        session, transcriber, queue = self.start(vad=True, finalize=finalize)
        worker = session._print_transcript
        queue.put((b"\1\0", datetime.now(), "silence"))
        self.assertTrue(entered.wait(1))
        original_stop = queue.stop

        def stop():
            original_stop()
            stopped.set()

        stopper = Thread(target=session._stop)
        with patch.object(queue, "stop", stop):
            try:
                for _ in range(30):
                    putDroppingOldestOnFull(queue, (b"\2\0", datetime.now(), "silence"))
                stopper.start()
                self.assertTrue(stopped.wait(1))
                for _ in range(30):
                    putDroppingOldestOnFull(queue, (b"\3\0", datetime.now(), "silence"))
                started = perf_counter()
                release.set()
                stopper.join(0.5)
                self.assertFalse(stopper.is_alive())
                self.assertLess(perf_counter() - started, 0.5)
                self.assertFalse(worker.is_alive())
                transcriber._finalizeAndTranscribe.assert_called_once()
                self.assertFalse(queue.waitForWork(None))
            finally:
                release.set()
                stopper.join(1)

    def test_device_error_wakes_idle_wait_without_config_snapshot(self):
        session, transcriber, queue = self.start()
        received = Queue()
        session.transcript_fnc = received.put
        recorder = session._recorder
        recorder.device_error_event.set()
        result = received.get(timeout=1)
        self.assertIn("error_code", result)
        self.assertEqual(sum(self.config.reads.values()), 0)
        transcriber._finalizeAndTranscribe.assert_not_called()
        session._stop()

    def test_stop_interrupts_pending_phrase_deadline(self):
        session, transcriber, queue = self.start(timeout=30)
        queue.put((b"\1\0", datetime.now()))
        self.assertGreater(queue.waits.get(timeout=1), 29)
        started = perf_counter()
        self.assertFalse(session._stop())
        self.assertLess(perf_counter() - started, 0.5)
        transcriber._finalizeAndTranscribe.assert_called_once()

    def test_recorder_overflow_diagnostics_with_notification_queue(self):
        for recorder_cls in (BaseEnergyAndAudioRecorder, BaseVadAndAudioRecorder):
            with self.subTest(recorder=recorder_cls.__name__):
                if recorder_cls is BaseEnergyAndAudioRecorder:
                    recorder = recorder_cls(FakeRecorder(), 300, False, 3, 5)
                    listener = "listen_energy_and_audio_in_background"
                else:
                    recorder = recorder_cls(FakeRecorder(), record_timeout=5, label="mic")
                    listener = "listen_with_segmenter_in_background"
                captured = {}

                def listen(**kwargs):
                    captured.update(kwargs)
                    return Mock(), Mock(), Mock()

                recorder.recorder = Mock()
                getattr(recorder.recorder, listener).side_effect = listen
                queue = _AudioQueue()
                recorder.recordIntoQueue(queue)
                from models.transcription.utterance_diagnostics import UtteranceDiagnostics
                log = Mock()
                diagnostics = UtteranceDiagnostics(log=log)
                with patch("models.transcription.transcription_recorder.utterance_diagnostics", diagnostics):
                    for i in range(21):
                        frame = Mock(segment_reason="silence")
                        frame.get_raw_data.return_value = bytes([i, 0])
                        captured["callback"](None, frame)
                    log.assert_called_once_with(
                        "audio_queue is full; dropped the oldest queued chunk to keep up [source=mic]"
                    )
                self.assertEqual(queue.qsize(), 20)
                self.assertEqual([queue.get_nowait()[0][0] for _ in range(20)], list(range(1, 21)))

    def test_bounds_drop_oldest_and_stopped_queue_remain_compatible(self):
        queue = _AudioQueue()
        dropped = [putDroppingOldestOnFull(queue, i) for i in range(30)]
        self.assertEqual(sum(dropped), 10)
        self.assertEqual(queue.maxsize, 20)
        self.assertEqual([queue.get_nowait() for _ in range(20)], list(range(10, 30)))
        queue.stop()
        queue.put(31)
        self.assertFalse(queue.waitForWork(None))

    def test_deadline_uses_existing_strict_wall_clock_boundary(self):
        _, transcriber, _ = self.start()
        spoken = datetime.now()
        transcriber.audio_sources.update(last_sample=b"\1\0", last_spoken=spoken)
        with patch("models.transcription.transcription_transcriber.datetime") as clock:
            clock.now.return_value = spoken + timedelta(seconds=3)
            self.assertEqual(transcriber.getAudioWaitTimeout(), 0.000001)
            clock.now.return_value += timedelta(seconds=1)
            self.assertEqual(transcriber.getAudioWaitTimeout(), 0)
