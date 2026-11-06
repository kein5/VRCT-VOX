import unittest
from unittest.mock import MagicMock

from models.translation.translation_translator import Translator


class FakeHypothesis:
    def __init__(self, tokens: list[str]) -> None:
        self.hypotheses = [tokens]


class FakeTokenizer:
    eos_token = "</s>"

    def __init__(self) -> None:
        self.src_lang = None
        self.lang_code_to_token = {"en": "__en__"}

    def encode(self, message: str, **kwargs) -> list[str]:
        return list(message)

    def convert_ids_to_tokens(self, ids: list[str]) -> list[str]:
        return ids

    def convert_tokens_to_ids(self, tokens: list[str]) -> list[str]:
        return tokens

    def decode(self, ids: list[str]) -> str:
        return "".join(ids)


class TestTranslateCTranslate2Dispatch(unittest.TestCase):
    def setUp(self) -> None:
        self.translator = Translator()
        self.translator.is_loaded_ctranslate2_model = True
        self.translator._ctranslate2_model_parameters = {"model_type": "m2m100_418M-ct2-int8"}
        self.translator.ctranslate2_tokenizer = FakeTokenizer()
        self.translator.ctranslate2_translator = MagicMock()
        self.translator.ctranslate2_translator.translate_batch.return_value = [
            FakeHypothesis(["_prefix_", "h", "i", "</s>"])
        ]

    def test_m2m100_uses_lang_code_to_token(self) -> None:
        self.translator.translateCTranslate2("hi", "ja", "en", "m2m100_418M-ct2-int8")
        _, kwargs = self.translator.ctranslate2_translator.translate_batch.call_args
        self.assertEqual(kwargs["target_prefix"], [["__en__"]])

    def test_nllb_600m_uses_raw_language_code_as_prefix(self) -> None:
        self.translator._ctranslate2_model_parameters = {"model_type": "nllb-200-distilled-600M-ct2-int8"}
        self.translator.translateCTranslate2(
            "hi", "jpn_Jpan", "eng_Latn", "nllb-200-distilled-600M-ct2-int8"
        )
        _, kwargs = self.translator.ctranslate2_translator.translate_batch.call_args
        self.assertEqual(kwargs["target_prefix"], [["eng_Latn"]])

    def test_oversized_source_fails_before_inference(self) -> None:
        result = self.translator.translateCTranslate2("x" * 1025, "ja", "en", "m2m100_418M-ct2-int8")
        self.assertIs(result, False)
        self.translator.ctranslate2_translator.translate_batch.assert_not_called()

    def test_source_at_limit_is_not_truncated(self) -> None:
        result = self.translator.translateCTranslate2("x" * 1024, "ja", "en", "m2m100_418M-ct2-int8")
        self.assertEqual(result, "hi")
        args, kwargs = self.translator.ctranslate2_translator.translate_batch.call_args
        self.assertEqual(len(args[0][0]), 1024)
        self.assertEqual(kwargs["max_input_length"], 0)
        self.assertEqual(kwargs["max_decoding_length"], 256)
        self.assertTrue(kwargs["return_end_token"])

    def test_output_without_end_token_is_failure(self) -> None:
        for length in (2, 255, 256):
            with self.subTest(length=length):
                self.translator.ctranslate2_translator.translate_batch.return_value = [
                    FakeHypothesis(["_prefix_", *(["x"] * length)])
                ]
                result = self.translator.translateCTranslate2("hi", "ja", "en", "m2m100_418M-ct2-int8")
                self.assertIs(result, False)

    def test_complete_output_at_limit_keeps_text_without_special_tokens(self) -> None:
        self.translator.ctranslate2_translator.translate_batch.return_value = [
            FakeHypothesis(["_prefix_", *(["x"] * 254), "</s>"])
        ]
        result = self.translator.translateCTranslate2("hi", "ja", "en", "m2m100_418M-ct2-int8")
        self.assertEqual(result, "x" * 254)

    def test_unknown_weight_type_returns_false(self) -> None:
        self.translator._ctranslate2_model_parameters = {"model_type": "unknown-weight"}
        result = self.translator.translateCTranslate2(
            "hi", "ja", "en", "unknown-weight"
        )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
