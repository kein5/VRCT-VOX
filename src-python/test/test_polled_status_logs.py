"""定期的に問い合わせる状態は、成功した応答を process.log に書かない。

UI は音声や配布の状態を 0.5〜1 秒ごとに問い合わせる。1 回ごとに受信・結果・応答の
3 行を書いていたため、何もしていなくても 1 時間に約 12 MB 増え、10 MB で切り詰め
られる process.log から起動時やエラーの記録が押し出されていた。
"""

import json
import logging
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import mainloop as mainloop_module
import utils
from mainloop import Main

POLL = "/get/data/voice_status"


class PolledResponseLogTests(unittest.TestCase):
    def setUp(self):
        original = utils.process_logger
        logger = logging.getLogger("test_polled_status_logs")
        logger.handlers.clear()
        logger.addHandler(logging.Handler())
        utils.process_logger = logger
        self.addCleanup(setattr, utils, "process_logger", original)

    def test_successful_polls_reach_the_ui_without_being_logged(self):
        logged, written = [], []
        utils.process_logger.info = logged.append
        with patch.object(utils, "_enqueueResponseLine", written.append):
            utils.printResponse(200, POLL, {"active": False})
            utils.printResponse(500, POLL, {"error": "voice_status_failed"})
            utils.printResponse(200, "/get/data/voice_settings", {"routing": "external"})
        self.assertEqual([json.loads(line)["endpoint"] for line in written], [POLL, POLL, "/get/data/voice_settings"])
        self.assertEqual([(entry["status"], entry["endpoint"]) for entry in logged],
                         [(500, POLL), (200, "/get/data/voice_settings")])

    def test_volume_meter_samples_reach_the_ui_without_being_logged(self):
        logged, written = [], []
        utils.process_logger.info = logged.append
        with patch.object(utils, "_enqueueResponseLine", written.append):
            for value in (0, 12, 0):
                utils.printResponse(200, "/run/check_mic_volume", value)
                utils.printResponse(200, "/run/check_speaker_volume", value)
        self.assertEqual(len(written), 6)
        self.assertEqual(logged, [])

    def test_a_response_that_cannot_be_serialized_logs_only_its_shape(self):
        errors, written = [], []
        utils.process_logger.info = lambda record: None
        utils.process_logger.error = errors.append
        with patch.object(utils, "_enqueueResponseLine", written.append), patch.object(utils, "errorLogging"):
            utils.printResponse(200, "/run/realtime_caption", {"text": "private caption", "bad": object()})
            utils.printResponse(200, "/get/data/voice_settings", {"nested": {"api_key": "sk-secret"}, "bad": {1, 2}})
        self.assertEqual([json.loads(line)["status"] for line in written], [500, 500])
        self.assertNotIn("private caption", " ".join(errors))
        self.assertNotIn("sk-secret", " ".join(errors))
        self.assertIn("/run/realtime_caption", errors[0])
        self.assertIn("'text': 'str'", errors[0])

    def test_every_quiet_endpoint_is_one_the_ui_polls(self):
        logics = Path(__file__).resolve().parents[2] / "src-ui/logics"
        source = (logics / "useReceiveRoutes.js").read_text(encoding="utf-8").replace("'", '"')
        # Settings routes are generated from base_endpoint_name entries.
        generated = (logics / "configs/config_page_setter/ui_config_setter.js").read_text(encoding="utf-8").replace("'", '"')
        for endpoint in utils.POLLED_ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                base = endpoint.removeprefix("/get/data/")
                self.assertTrue(f'"{endpoint}"' in source or f'base_endpoint_name: "{base}"' in generated, endpoint)


class PolledRequestLogTests(unittest.TestCase):
    def _run(self, endpoint, status):
        main = Main(controller_instance=MagicMock(), mapping_data={
            endpoint: {"status": True, "variable": lambda data: {"status": status, "result": {"ok": status == 200}}}})
        main._stop_event.clear()
        responses, logs = [], []
        with patch.object(mainloop_module, "printResponse", side_effect=lambda s, ep, result: responses.append((s, ep))), \
                patch.object(mainloop_module, "printLog", side_effect=lambda log, data=None: logs.append(log)):
            main.queue.put((endpoint, None, 0))
            worker = threading.Thread(target=main.handler, daemon=True)
            worker.start()
            deadline = time.time() + 2
            while not responses and time.time() < deadline:
                time.sleep(0.01)
            main._stop_event.set()
            worker.join(timeout=2)
        return responses, logs

    def test_a_successful_poll_logs_nothing_but_still_answers(self):
        responses, logs = self._run(POLL, 200)
        self.assertEqual(responses, [(200, POLL)])
        self.assertEqual(logs, [])

    def test_a_failed_poll_and_other_requests_are_still_logged(self):
        self.assertEqual(self._run(POLL, 500)[1], [POLL])
        self.assertEqual(self._run("/get/data/voice_settings", 200)[1], ["/get/data/voice_settings"])


if __name__ == "__main__":
    unittest.main()
