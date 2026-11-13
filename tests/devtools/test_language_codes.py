"""Keep UI display metadata in step with the authoritative transcription table."""

import unittest

from tools.language_codes import OUTPUT, language_codes, render


class LanguageCodesTests(unittest.TestCase):
    def test_generated_table_is_current(self):
        self.assertEqual(OUTPUT.read_text(encoding="utf-8"), render())

    def test_every_transcription_pair_has_a_tag(self):
        for language, countries in language_codes().items():
            for country, code in countries.items():
                with self.subTest(language=language, country=country):
                    self.assertRegex(code or "", r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?-[A-Z]{2}$")
