"""Ollama への要求は、どれも時間を区切る。

起動時の確認は `/api/tags` の応答を待つ。根元の確認には答えたのに
`/api/tags` の応答が止まったサーバーで、起動が終わらなくならないようにする。
"""

import unittest
from unittest.mock import MagicMock, patch

from models.translation import translation_ollama


class OllamaTimeoutTests(unittest.TestCase):
    def test_model_list_request_has_a_timeout(self) -> None:
        response = MagicMock()
        response.json.return_value = {"models": [{"name": "b"}, {"name": "a"}]}
        with patch.object(translation_ollama.requests, "get", return_value=response) as get:
            models = translation_ollama._get_available_text_models("http://localhost:11434")

        self.assertEqual(models, ["a", "b"])
        self.assertGreater(get.call_args.kwargs.get("timeout") or 0, 0)

    def test_model_list_is_empty_when_the_request_times_out(self) -> None:
        with patch.object(translation_ollama.requests, "get",
                          side_effect=translation_ollama.requests.exceptions.Timeout()):
            self.assertEqual(translation_ollama._get_available_text_models("http://localhost:11434"), [])


if __name__ == "__main__":
    unittest.main()
