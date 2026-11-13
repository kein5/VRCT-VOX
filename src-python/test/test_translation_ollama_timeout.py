"""Ollama への要求は、どれも時間を区切る。

起動時の確認は `/api/tags` の応答を待つ。根元の確認には答えたのに
`/api/tags` の応答が止まったサーバーで、起動が終わらなくならないようにする。
"""

import unittest
import requests
from unittest.mock import MagicMock, patch

from models.translation import translation_lmstudio, translation_ollama


class OllamaTimeoutTests(unittest.TestCase):
    def test_model_list_request_has_a_timeout(self) -> None:
        response = MagicMock()
        response.json.return_value = {"models": [{"name": "b"}, {"name": "a"}]}
        with patch.object(translation_ollama, "api_request", return_value=response) as get:
            models = translation_ollama._get_available_text_models("http://localhost:11434")

        self.assertEqual(models, ["a", "b"])
        self.assertGreater(get.call_args.kwargs.get("timeout") or 0, 0)

    def test_model_list_is_empty_when_the_request_times_out(self) -> None:
        with patch.object(translation_ollama, "api_request",
                          side_effect=requests.exceptions.Timeout()):
            self.assertEqual(translation_ollama._get_available_text_models("http://localhost:11434"), [])


class LocalEngineNotRunningTests(unittest.TestCase):
    ENGINES = (translation_ollama, translation_lmstudio)

    def check(self, engine, failure):
        with patch.object(engine, "api_request", side_effect=failure), patch.object(engine, "errorLogging") as logged:
            self.assertIs(engine._authentication_check("http://localhost:1"), False)
        return logged

    def test_a_stopped_engine_is_not_an_error(self) -> None:
        for engine in self.ENGINES:
            for failure in (requests.exceptions.ConnectTimeout(), requests.exceptions.ConnectionError()):
                with self.subTest(engine=engine.__name__, failure=type(failure).__name__):
                    self.check(engine, failure).assert_not_called()

    def test_other_failures_are_still_recorded(self) -> None:
        for engine in self.ENGINES:
            for failure in (requests.exceptions.ReadTimeout(), ValueError("bad url")):
                with self.subTest(engine=engine.__name__, failure=type(failure).__name__):
                    self.check(engine, failure).assert_called_once()


if __name__ == "__main__":
    unittest.main()
