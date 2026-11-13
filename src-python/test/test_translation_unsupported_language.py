import unittest
from unittest.mock import MagicMock, patch

from models.transcription.transcription_languages import transcription_lang
from models.translation.translation_languages import loadTranslationLanguages
from models.translation.translation_translator import Translator, UnsupportedLanguageError


def setUpModule() -> None:
    # `translation_lang` is filled by config.py at startup, so running this
    # file on its own used to leave it empty and turn every lookup into an
    # UnsupportedLanguageError. Load it here so the file stands alone.
    loadTranslationLanguages(path=".")


class TestGetLanguageCodeUnsupportedLanguage(unittest.TestCase):
    """Bug report: selecting a language a translator doesn't support must not
    look like a translator-engine failure (rate limit / auth / network)."""

    def test_unsupported_source_language_raises_unsupported_language_error(self) -> None:
        # DeepL_API has no "Arabic" entry (see docs/kiroku bug report logs:
        # repeated `KeyError: 'Arabic'` at translation_translator.py:498).
        with self.assertRaises(UnsupportedLanguageError):
            Translator.getLanguageCode(
                translator_name="DeepL_API",
                weight_type="",
                target_country="Japan",
                source_language="Arabic",
                target_language="Japanese",
            )

    def test_supported_language_pair_resolves_normally(self) -> None:
        source, target = Translator.getLanguageCode(
            translator_name="DeepL_API",
            weight_type="",
            target_country="Japan",
            source_language="English",
            target_language="Japanese",
        )
        self.assertIsInstance(source, str)
        self.assertIsInstance(target, str)


class TestTranslateReturnsNoneForUnsupportedLanguage(unittest.TestCase):
    def setUp(self) -> None:
        self.translator = Translator.__new__(Translator)

    def test_translate_returns_none_not_false_for_unsupported_language(self) -> None:
        result = self.translator.translate(
            translator_name="DeepL_API",
            weight_type="",
            source_language="Arabic",
            target_language="Japanese",
            target_country="Japan",
            message="hello",
        )
        self.assertIsNone(result)

    @patch("models.translation.translation_translator.errorLogging")
    def test_translate_returns_false_on_real_backend_failure(self, mock_log: MagicMock) -> None:
        with patch(
            "models.translation.translation_translator.other_web_Translator",
            side_effect=RuntimeError("network down"),
        ), patch("models.translation.translation_translator.ENABLE_TRANSLATORS", True):
            result = self.translator.translate(
                translator_name="Bing",
                weight_type="",
                source_language="English",
                target_language="Japanese",
                target_country="Japan",
                message="hello",
            )
        self.assertFalse(result)
        self.assertIsNotNone(result)  # False, not None: this must still look like an engine failure
        mock_log.assert_called_once_with(provider="Bing")


class TestTranslateNeverReportsAnUnreachableEngineAsSuccess(unittest.TestCase):
    """A branch that never ran must not come back as an empty success.

    `getTranslate` decides success with `isinstance(translation, str)`, so a
    "" leaking out of `translate()` is reported as a successful translation of
    nothing: no CTranslate2 fallback, no error log, and nothing the user sees
    except empty output.
    """

    def setUp(self) -> None:
        self.translator = Translator.__new__(Translator)

    def test_web_engine_returns_false_when_the_backend_is_unavailable(self) -> None:
        # What an offline start used to look like: the import failed, so the
        # Google/Bing/Papago branches are skipped entirely.
        with patch(
            "models.translation.translation_translator.ENABLE_TRANSLATORS", False
        ), patch("models.translation.translation_translator.other_web_Translator", None):
            for engine in ("Google", "Bing", "Papago"):
                with self.subTest(engine=engine):
                    result = self.translator.translate(
                        translator_name=engine,
                        weight_type="",
                        source_language="English",
                        target_language="Japanese",
                        target_country="Japan",
                        message="hello",
                    )
                    self.assertIs(result, False)

    def test_deepl_returns_false_without_an_authenticated_client(self) -> None:
        self.translator.deepl_client = None
        result = self.translator.translate(
            translator_name="DeepL_API",
            weight_type="",
            source_language="English",
            target_language="Japanese",
            target_country="Japan",
            message="hello",
        )
        self.assertIs(result, False)

    @patch("models.translation.translation_translator.ENABLE_TRANSLATORS", False)
    @patch("models.translation.translation_translator.other_web_Translator", None)
    def test_authenticated_deepl_works_without_the_web_extension(self) -> None:
        translator = Translator()
        translator.deepl_client = MagicMock()
        translator.deepl_client.translate_text.return_value.text = "こんにちは"
        result = translator.translate(
            translator_name="DeepL_API", weight_type="", source_language="English",
            target_language="Japanese", target_country="Japan", message="hello",
        )
        self.assertEqual(result, "こんにちは")
        translator.deepl_client.translate_text.assert_called_once_with(
            "hello", source_lang="en", target_lang="ja",
        )

    @patch("models.translation.translation_translator.ENABLE_TRANSLATORS", False)
    @patch("models.translation.translation_translator.errorLogging")
    def test_deepl_backend_failure_is_reported_without_the_web_extension(self, mock_log) -> None:
        translator = Translator()
        translator.deepl_client = MagicMock()
        translator.deepl_client.translate_text.side_effect = RuntimeError("provider failure")
        result = translator.translate(
            translator_name="DeepL_API", weight_type="", source_language="English",
            target_language="Japanese", target_country="Japan", message="hello",
        )
        self.assertIs(result, False)
        translator.deepl_client.translate_text.assert_called_once()
        mock_log.assert_called_once_with(provider="DeepL_API")

    def test_unknown_translator_name_never_returns_an_empty_string(self) -> None:
        # E.g. a config naming an engine this build dropped. It never reaches
        # the `match`: getLanguageCode runs first and finds no language table
        # for the name, so it surfaces as an unsupported pair (None) and the
        # caller passes the original text through. Either way, not "".
        result = self.translator.translate(
            translator_name="NoSuchEngine",
            weight_type="",
            source_language="English",
            target_language="Japanese",
            target_country="Japan",
            message="hello",
        )
        self.assertIsNone(result)

    def test_same_language_still_returns_the_original_message(self) -> None:
        result = self.translator.translate(
            translator_name="Google",
            weight_type="",
            source_language="Japanese",
            target_language="Japanese",
            target_country="Japan",
            message="こんにちは",
        )
        self.assertEqual(result, "こんにちは")


class TestFilipinoLanguageMapping(unittest.TestCase):
    providers = [
        ("CTranslate2", "nllb-200-distilled-600M-ct2-int8", "tgl_Latn", "eng_Latn"),
        ("CTranslate2", "nllb-200-distilled-1.3B-ct2-int8", "tgl_Latn", "eng_Latn"),
        ("CTranslate2", "nllb-200-3.3B-ct2-int8", "tgl_Latn", "eng_Latn"),
        *[(engine, "", "Tagalog", "English") for engine in (
            "OpenAI_API", "OpenAI_Compatible", "Groq_API", "OpenRouter_API", "LMStudio", "Ollama",
        )],
    ]

    def test_canonical_filipino_resolves_as_source_and_target(self) -> None:
        self.assertIn("Philippines", transcription_lang["Filipino"])
        for engine, weight, filipino, english in self.providers:
            with self.subTest(engine=engine, weight=weight):
                self.assertEqual(
                    Translator.getLanguageCode(engine, weight, "United States", "Filipino", "English"),
                    (filipino, english),
                )
                self.assertEqual(
                    Translator.getLanguageCode(engine, weight, "Philippines", "English", "Filipino"),
                    (english, filipino),
                )

    def test_legacy_tagalog_key_still_resolves(self) -> None:
        for engine, weight, tagalog, english in self.providers:
            with self.subTest(engine=engine, weight=weight):
                self.assertEqual(
                    Translator.getLanguageCode(engine, weight, "United States", "Tagalog", "English"),
                    (tagalog, english),
                )
                self.assertEqual(
                    Translator.getLanguageCode(engine, weight, "Philippines", "English", "Tagalog"),
                    (english, tagalog),
                )


if __name__ == "__main__":
    unittest.main()
