"""Speech diagnostics use event-driven windows, bounded samples and no private data."""

import json
import threading
import unittest
from datetime import datetime
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from models.transcription.utterance_diagnostics import (
    SAMPLE_LIMIT, SLOW_MS, UtteranceDiagnostics,
)


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.logs = []
        self.diagnostics = UtteranceDiagnostics(clock=lambda: self.now, log=self.logs.append)

    def test_lazy_interval_counts_percentiles_and_no_catch_up(self):
        for value in range(1, 101):
            self.diagnostics.record("mic", "asr_success", {"asr_ms": value}, "routine")
        self.now = 59.999
        self.assertEqual(self.logs, [])
        self.now = 60
        self.diagnostics.record("mic", "speech_start")
        self.assertEqual(len(self.logs), 1)
        self.assertIn("asr_success=100", self.logs[0])
        self.assertIn("asr_ms(n=100,samples=100,p50=50.0,p95=95.0,max=100.0)", self.logs[0])
        self.now = 600
        self.diagnostics.record("mic", "speech_start")
        self.assertEqual(len(self.logs), 2)
        self.assertIn("speech_start=1", self.logs[1])

    def test_no_activity_no_reports_threads_or_timers(self):
        with patch.object(threading, "Thread", side_effect=AssertionError("new thread")), \
                patch.object(threading, "Timer", side_effect=AssertionError("new timer")):
            diagnostics = UtteranceDiagnostics(clock=lambda: self.now, log=self.logs.append)
            for self.now in (0, 60, 6000):
                diagnostics.queue_result("mic", False)
                diagnostics.flush(reason="shutdown")
            self.assertEqual(self.logs, [])
            diagnostics.record("mic", "asr_success", {"asr_ms": 100})
            diagnostics.flush("mic")
            self.assertEqual(len(self.logs), 1)
            diagnostics.flush("mic")
            self.assertEqual(len(self.logs), 1)

    def test_every_stage_threshold_retains_exact_detail(self):
        for stage, limit in SLOW_MS.items():
            with self.subTest(stage=stage):
                self.logs.clear()
                self.diagnostics.record("mic", "message", {stage: limit - 1}, "detail below")
                self.assertEqual(self.logs, [])
                self.diagnostics.record("mic", "message", {stage: limit}, "original full detail")
                self.assertEqual(self.logs, ["original full detail"])

    def test_drop_onset_interval_count_recovery_and_stop_without_recovery(self):
        for _ in range(10):
            self.diagnostics.queue_result("mic", True)
        self.assertEqual(self.logs, ["audio_queue is full; dropped the oldest queued chunk to keep up [source=mic]"])
        self.now = 60
        self.diagnostics.queue_result("mic", True)
        self.assertIn("audio_drop=10", self.logs[1])
        self.assertIn("drop_run=10", self.logs[1])
        self.diagnostics.queue_result("mic", False)
        self.assertEqual(self.logs[-1], "[ASR-queue][mic] recovered dropped=11 repeated=10")
        size = len(self.logs)
        self.diagnostics.queue_result("mic", False)
        self.assertEqual(len(self.logs), size)
        self.diagnostics.queue_result("mic", True)
        self.diagnostics.queue_result("mic", True)
        self.diagnostics.flush("mic")
        self.assertIn("stop dropped=2 repeated=1 recovery=unconfirmed", self.logs[-1])
        self.diagnostics.flush(reason="shutdown")
        self.assertEqual(len(self.logs), size + 3)

    def test_sources_on_two_threads_are_independent_and_bounded(self):
        barrier = threading.Barrier(3)

        def produce(source, value):
            barrier.wait()
            for _ in range(20000):
                self.diagnostics.record(source, "asr_success", {"asr_ms": value})

        workers = [threading.Thread(target=produce, args=(source, value))
                   for source, value in (("mic", 100), ("speaker", 200))]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(self.logs, [])
        for state in self.diagnostics._sources.values():
            self.assertEqual(len(state.stages["asr_ms"].values), SAMPLE_LIMIT)
            self.assertEqual(state.stages["asr_ms"].count, 20000)
        self.diagnostics.flush(reason="shutdown")
        for source, value in (("mic", 100), ("speaker", 200)):
            row = next(row for row in self.logs if f"][{source}]" in row)
            self.assertIn("asr_success=20000", row)
            self.assertIn(f"p50={value:.1f},p95={value:.1f},max={value:.1f}", row)

    def test_recovery_at_interval_does_not_start_an_empty_window(self):
        self.diagnostics.queue_result("mic", True)
        self.now = 60
        self.diagnostics.queue_result("mic", False)
        self.assertEqual(len(self.logs), 3)  # onset, count summary, recovery
        self.now = 160
        for _ in range(2):
            self.diagnostics.record("mic", "asr_success", {"asr_ms": 100})
        self.assertEqual(len(self.logs), 3)
        self.now = 220
        self.diagnostics.record("mic", "speech_start")
        self.assertEqual(len(self.logs), 4)
        self.assertIn("window=60.0s asr_success=2", self.logs[-1])

    def test_same_source_concurrent_writers_and_flush_do_not_lose_counts(self):
        def produce():
            for _ in range(2000):
                self.diagnostics.record("mic", "speech_start")

        workers = [threading.Thread(target=produce) for _ in range(2)]
        for worker in workers:
            worker.start()
        for _ in range(30):
            self.diagnostics.flush("mic")
        for worker in workers:
            worker.join(5)
            self.assertFalse(worker.is_alive())
        self.diagnostics.flush("mic")
        self.assertEqual(sum(int(row.split("speech_start=")[1].split()[0]) for row in self.logs), 4000)

    def test_window_max_includes_evicted_samples_and_keys_are_bounded(self):
        self.diagnostics.record("mic", "asr_success", {"asr_ms": 9000})
        for i in range(20000):
            self.diagnostics.record("mic", "asr_success", {"asr_ms": 1, str(i): 7})
            self.diagnostics.record(str(i), str(i), {str(i): 1})
            self.diagnostics.record("mic", str(i), {str(i): 1})
        self.diagnostics.flush("mic")
        self.assertIn("n=20001,samples=256,p50=1.0,p95=1.0,max=9000.0", self.logs[0])
        self.assertEqual(len(self.diagnostics._sources), 2)

    def test_one_summary_means_one_process_record_and_one_status_348(self):
        import utils
        records, stdout = [], []
        diagnostics = UtteranceDiagnostics(clock=lambda: self.now, log=utils.printLog)
        with patch.object(utils, "process_logger", SimpleNamespace(info=records.append)), \
                patch.object(utils, "_enqueueLogLine", stdout.append):
            for _ in range(30):
                diagnostics.record("mic", "asr_success", {"asr_ms": 100}, "[ASR-stats] routine")
            self.assertEqual(records, [])
            self.assertEqual(stdout, [])
            self.now = 60
            diagnostics.record("mic", "speech_start")
        self.assertEqual(len(records), 1)
        self.assertEqual(len(stdout), 1)
        self.assertEqual(json.loads(stdout[0]), records[0])
        self.assertEqual(records[0]["status"], 348)
        self.assertIn("asr_success=30", records[0]["log"])


class PipelineDiagnosticsTests(unittest.TestCase):
    setUp = DiagnosticsTests.setUp
    def _patch(self, module):
        patcher = patch.object(module, "utterance_diagnostics", self.diagnostics)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _recorder(self, vad):
        from models.transcription import transcription_recorder as module
        self._patch(module)
        source = SimpleNamespace(SAMPLE_RATE=16000, SAMPLE_WIDTH=2, channels=1)
        if vad:
            recorder = module.BaseVadAndAudioRecorder(source, 3, label="mic")
            method = "listen_with_segmenter_in_background"
        else:
            recorder = module.BaseEnergyAndAudioRecorder(source, 100, False, 3, 3, label="mic")
            method = "listen_energy_and_audio_in_background"
        listener = MagicMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
        setattr(recorder.recorder, method, listener)
        queue = Queue(maxsize=1)
        recorder.recordIntoQueue(queue)
        return recorder, queue, listener.call_args.kwargs["callback"]

    def test_both_recorder_drop_paths_and_stop_flush(self):
        for vad in (False, True):
            with self.subTest(vad=vad):
                self.logs.clear()
                recorder, queue, callback = self._recorder(vad)
                audio = SimpleNamespace(get_raw_data=lambda: b"\0\0", segment_reason="silence")
                for _ in range(4):
                    callback(None, audio)
                self.assertEqual(len(self.logs), 1)
                queue.get_nowait()
                callback(None, audio)
                self.assertIn("recovered dropped=3 repeated=2", self.logs[-1])
                recorder.stop()
                self.assertIn("audio_drop=3", self.logs[-1])
                self.assertIn("reason=stop", self.logs[-1])

    def test_vad_routine_and_delayed_hangover_keep_segment_detail(self):
        from models.transcription.audio_vad import VadSegmenter
        frame = b"\0\0" * 512
        vad = VadSegmenter(probability=lambda _: 0, diagnostic_label="mic",
                           diagnostic_observer=self.diagnostics.record)
        for probability in [1, 1] + [0] * 25:
            vad._process_frame(frame, probability)
        self.assertEqual(self.logs, [])
        # Intermediate probabilities preserve the silence anchor. This waits
        # beyond twice the ordinary 768 ms hangover, then ends on low energy.
        for probability in [1, 1, 0] + [.15] * 50 + [0]:
            vad._process_frame(frame, probability)
        self.assertEqual(len(self.logs), 1)
        for field in ("speech_end segment_id=", "reason=silence", "duration_ms=", "frames=", "wait_ms=1632.0"):
            self.assertIn(field, self.logs[0])
        self.diagnostics.flush("mic")
        self.assertIn("speech_start=2", self.logs[-1])
        self.assertIn("speech_end=2", self.logs[-1])

    def test_routine_legacy_utterances_merge_and_asr_are_summarized(self):
        from models.transcription import transcription_transcriber as module
        self._patch(module)
        transcriber = module.AudioTranscriber(False, SimpleNamespace(
            SAMPLE_RATE=16000, SAMPLE_WIDTH=2, channels=1), 3, 10, "Google", vad_segmented=True)
        transcriber._resolve_provider = lambda: SimpleNamespace(transcribe=lambda *a, **k: ("PRIVATE TEXT", .9, True))
        with patch.object(module.time, "perf_counter", return_value=0), patch.object(module, "printLog") as errors:
            for _ in range(30):
                queue = Queue()
                queue.put((b"\0\0", datetime.now(), "silence"))
                transcriber.transcribeAudioQueue(queue, ["English"], ["United States"])
            errors.assert_not_called()
        self.assertEqual(self.logs, [])
        self.now = 60
        self.diagnostics.record("mic", "speech_start")
        self.assertEqual(len(self.logs), 1)
        self.assertIn("vad_finalize=30", self.logs[0])
        self.assertIn("asr_success=30", self.logs[0])
        self.assertNotIn("PRIVATE", self.logs[0])

    def test_no_match_and_provider_failure_remain_visible(self):
        from models.transcription import transcription_transcriber as module
        from errors import AudioPipelineError
        self._patch(module)
        transcriber = module.AudioTranscriber(False, SimpleNamespace(
            SAMPLE_RATE=16000, SAMPLE_WIDTH=2, channels=1), 3, 10, "Google")
        provider = MagicMock()
        provider.transcribe.return_value = ("", 0, False)
        transcriber._resolve_provider = lambda: provider
        with patch.object(module.time, "perf_counter", return_value=0), \
                patch.object(module, "printLog", side_effect=self.logs.append), \
                patch.object(module, "errorLogging") as errors:
            transcriber._finalizeAndTranscribe(["English"], ["United States"], -.8, .6, 0)
            self.assertIn("this_call=failure", self.logs[-1])
            self.assertIn("English=nomatch(0ms)", self.logs[-1])
            provider.transcribe.side_effect = RuntimeError("fake failure")
            with self.assertRaises(AudioPipelineError):
                transcriber._finalizeAndTranscribe(["English"], ["United States"], -.8, .6, 0)
            errors.assert_called_once()
            self.assertEqual(self.logs[-1], "[ASR-error][mic][Google] error_type=RuntimeError asr=0ms calls=1/1 [English=error]")

    def test_model_stop_and_controller_shutdown_flush_both_sources(self):
        import controller as controller_module
        import model as model_module
        self._patch(model_module)
        self._patch(controller_module)
        self.diagnostics.record("mic", "asr_success", {"asr_ms": 100})
        model_module.MicSession()._stop()
        self.assertIn("reason=stop", self.logs[-1])
        self.diagnostics.record("speaker", "message", {"translate_ms": 200})
        controller = controller_module.Controller.__new__(controller_module.Controller)
        controller._initRealtimeASR({})
        controller.mic_lifecycle_lock = threading.Lock()
        controller.speaker_lifecycle_lock = threading.Lock()
        with patch.object(controller_module, "model"), patch.object(controller_module, "device_manager"), \
                patch.object(controller_module, "config"):
            self.assertEqual(controller.shutdown()["status"], 200)
        self.assertEqual(len(self.logs), 2)
        self.assertIn("[speaker] reason=shutdown", self.logs[-1])

    def test_realtime_final_pending_metric_without_socket_or_event_loop(self):
        from models.transcription import speechcpp_realtime as module
        from models.transcription.realtime_events import PREFIX
        self._patch(module)
        client = module.SpeechCppRealtime("http://127.0.0.1:8080", "asr", "ja", "mic")
        client.state = "ready"
        events = iter([
            {"event_id": "1", "item_id": "private-id", "type": "input_audio_buffer.speech_started"},
            {"event_id": "2", "item_id": "private-id", "type": PREFIX + "completed", "transcript": "PRIVATE", "stop": "complete"},
        ])

        async def receive():
            event = next(events)
            if event["event_id"] == "2":
                self.now = 8
                client.state = "closed"
            return json.dumps(event)

        async def wait_for(awaitable, timeout):
            return await awaitable

        client._ws = SimpleNamespace(recv=receive)
        with patch.object(module, "monotonic", side_effect=lambda: self.now), \
                patch.object(module.asyncio, "wait_for", wait_for):
            coroutine = client._read()
            with self.assertRaises(StopIteration):
                coroutine.send(None)
        self.assertEqual(self.logs, ["[ASR-realtime][mic] state=final pending=8000.0ms"])
        self.assertEqual(client._updates.get_nowait().text, "PRIVATE")
        self.diagnostics.flush("mic")
        self.assertNotIn("PRIVATE", " ".join(self.logs))
        self.assertNotIn("private-id", " ".join(self.logs))

    def test_realtime_expiry_and_late_stop_flush_without_new_threads(self):
        from models.transcription import realtime_delivery as module
        from models.transcription.realtime_events import TranscriptUpdate
        self._patch(module)
        self.now = 100.5
        session = SimpleNamespace(source="speaker", is_current=lambda _: True, request_stop=lambda: None)
        published, errors = [], []

        def process(update, current):
            self.assertTrue(current())
            self.now = 103
            delivery.request_stop()
            return {"original": {"message": "PRIVATE"}, "translations": []}

        delivery = module.RealtimeDelivery(session, published.append, process, errors.append, clock=lambda: self.now)
        update = TranscriptUpdate("speaker", "owned", "u", 1, "PRIVATE", True, "final", received_ns=100_000_000_000)
        delivery._finals.put_nowait((update, 102, published.append, process))
        with patch.object(module, "Thread", side_effect=AssertionError("new thread")):
            delivery._translate()
            self.assertTrue(delivery.close())
        self.assertEqual(published, [])
        self.assertEqual(errors, [])
        self.assertEqual(len(self.logs), 2)
        self.assertEqual(self.logs[0], "[latency][speaker] realtime delivery=3000.0ms queue=500.0ms")
        self.assertIn("[speaker] reason=stop", self.logs[1])
        self.assertIn("realtime_queue_ms(n=1,samples=1,p50=500.0,p95=500.0,max=500.0)", self.logs[1])
        self.assertNotIn("PRIVATE", " ".join(self.logs))


if __name__ == "__main__":
    unittest.main()
