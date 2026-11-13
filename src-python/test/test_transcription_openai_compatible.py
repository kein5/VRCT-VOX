"""models/transcription/transcription_openai_compatible.py のテスト。

`OpenAI` SDK自体は信頼し、こちらの責務である「認証キーの有効性を
`models.list()` の成否で判定する」「取得したモデル一覧を
keyword_filter で絞り込む」の2点のみを検証する。
"""

import unittest
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from models.transcription.transcription_openai_compatible import (
    TRANSCRIPTION_MODEL_KEYWORDS,
    checkTranscriptionApiKey,
    getAvailableTranscriptionModels,
    transcriptionResponseFormat,
)


class TestCheckTranscriptionApiKey(unittest.TestCase):
    @patch("models.transcription.transcription_openai_compatible.OpenAI")
    def test_returns_true_when_models_list_succeeds(self, openai_cls) -> None:
        openai_cls.return_value.models.list.return_value = SimpleNamespace(data=[])

        result = checkTranscriptionApiKey("sk-test", "https://api.groq.com/openai/v1")

        self.assertTrue(result)
        openai_cls.assert_called_once_with(api_key="sk-test", base_url="https://api.groq.com/openai/v1",
                                          timeout=3.0, max_retries=0, http_client=ANY)
        openai_cls.return_value.close.assert_called_once()

    @patch("models.transcription.transcription_openai_compatible.OpenAI")
    def test_returns_false_when_models_list_raises(self, openai_cls) -> None:
        openai_cls.return_value.models.list.side_effect = Exception("invalid api key")

        result = checkTranscriptionApiKey("sk-bad", "https://api.groq.com/openai/v1")

        self.assertFalse(result)

    @patch("models.transcription.transcription_openai_compatible.OpenAI")
    def test_returns_false_when_client_construction_raises(self, openai_cls) -> None:
        openai_cls.side_effect = Exception("bad base_url")

        result = checkTranscriptionApiKey("sk-test", "not-a-url")

        self.assertFalse(result)


class TestGetAvailableTranscriptionModels(unittest.TestCase):
    def _mock_models(self, openai_cls, ids) -> None:
        openai_cls.return_value.models.list.return_value = SimpleNamespace(
            data=[SimpleNamespace(id=i) for i in ids]
        )

    @patch("models.transcription.transcription_openai_compatible.OpenAI")
    def test_returns_sorted_models_without_filter(self, openai_cls) -> None:
        self._mock_models(openai_cls, ["whisper-large-v3", "llama-3.1-8b"])

        result = getAvailableTranscriptionModels("sk-test", "https://api.groq.com/openai/v1")

        self.assertEqual(result, ["llama-3.1-8b", "whisper-large-v3"])

    @patch("models.transcription.transcription_openai_compatible.OpenAI")
    def test_keyword_filter_keeps_only_matching_models(self, openai_cls) -> None:
        self._mock_models(openai_cls, ["whisper-large-v3", "llama-3.1-8b", "distil-whisper-large-v3-en"])

        result = getAvailableTranscriptionModels(
            "sk-test", "https://api.groq.com/openai/v1", keyword_filter=["whisper"]
        )

        self.assertEqual(result, ["distil-whisper-large-v3-en", "whisper-large-v3"])

    @patch("models.transcription.transcription_openai_compatible.OpenAI")
    def test_keyword_filter_is_case_insensitive(self, openai_cls) -> None:
        self._mock_models(openai_cls, ["Whisper-Large-V3"])

        result = getAvailableTranscriptionModels(
            "sk-test", "https://api.groq.com/openai/v1", keyword_filter=["whisper"]
        )

        self.assertEqual(result, ["Whisper-Large-V3"])

    @patch("models.transcription.transcription_openai_compatible.OpenAI")
    def test_no_matches_returns_empty_list(self, openai_cls) -> None:
        self._mock_models(openai_cls, ["llama-3.1-8b"])

        result = getAvailableTranscriptionModels(
            "sk-test", "https://api.groq.com/openai/v1", keyword_filter=["whisper"]
        )

        self.assertEqual(result, [])


    @patch("models.transcription.transcription_openai_compatible.OpenAI")
    def test_keyword_filter_leaves_out_diarization_models(self, openai_cls) -> None:
        self._mock_models(openai_cls, ["gpt-4o-transcribe", "gpt-4o-transcribe-diarize", "whisper-1"])

        result = getAvailableTranscriptionModels(
            "sk-test", "https://api.openai.com/v1", keyword_filter=TRANSCRIPTION_MODEL_KEYWORDS
        )

        self.assertEqual(result, ["gpt-4o-transcribe", "whisper-1"])


class TestTranscriptionResponseFormat(unittest.TestCase):
    def test_gpt_transcribe_models_use_json(self) -> None:
        # OpenAI API reference: the only supported format for these is json.
        for model in ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "gpt-4o-mini-transcribe-2025-12-15"]:
            self.assertEqual(transcriptionResponseFormat(model), "json", model)

    def test_whisper_models_use_verbose_json(self) -> None:
        for model in ["whisper-1", "whisper-large-v3", "whisper-large-v3-turbo", "Systran/faster-whisper-small"]:
            self.assertEqual(transcriptionResponseFormat(model), "verbose_json", model)


if __name__ == "__main__":
    unittest.main()
