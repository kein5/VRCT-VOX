"""CTranslate2 weight licensing: M2M100 (MIT) is the default, NLLB
(CC-BY-NC-4.0) is opt-in only, and saved settings are left alone.

No network and no real weights: model downloads and the translator are
patched, and Config instances read/write a temporary config.json.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from config import Config, config
from controller import Controller
from model import model
from models.translation.translation_translator import Translator, UnsupportedLanguageError
from models.translation.translation_utils import (
    DEFAULT_CTRANSLATE2_WEIGHT_TYPE,
    ctranslate2_weights,
    isNonCommercialCTranslate2Weight,
)

M2M100 = "m2m100_418M-ct2-int8"
NLLB_600M = "nllb-200-distilled-600M-ct2-int8"
NLLB_1_3B = "nllb-200-distilled-1.3B-ct2-int8"

SRC_PYTHON = Path(__file__).resolve().parents[1]
REPO_ROOT = SRC_PYTHON.parent
LANGUAGES_YAML = SRC_PYTHON / "models" / "translation" / "translation_settings" / "languages" / "languages.yml"
UI_CONFIGS_JS = REPO_ROOT / "src-ui" / "logics" / "ui_configs.js"

# transformers 5.22.1 M2M100Tokenizer FAIRSEQ_LANGUAGE_CODES["m2m100"]. Copied so
# the check also runs where transformers isn't installed; compared against the
# installed library below when it is.
M2M100_TOKENIZER_CODES = {
    "af", "am", "ar", "ast", "az", "ba", "be", "bg", "bn", "br", "bs", "ca", "ceb", "cs", "cy", "da",
    "de", "el", "en", "es", "et", "fa", "ff", "fi", "fr", "fy", "ga", "gd", "gl", "gu", "ha", "he",
    "hi", "hr", "ht", "hu", "hy", "id", "ig", "ilo", "is", "it", "ja", "jv", "ka", "kk", "km", "kn",
    "ko", "lb", "lg", "ln", "lo", "lt", "lv", "mg", "mk", "ml", "mn", "mr", "ms", "my", "ne", "nl",
    "no", "ns", "oc", "or", "pa", "pl", "ps", "pt", "ro", "ru", "sd", "si", "sk", "sl", "so", "sq",
    "sr", "ss", "su", "sv", "sw", "ta", "th", "tl", "tn", "tr", "uk", "ur", "uz", "vi", "wo", "xh",
    "yi", "yo", "zh", "zu",
}


def _isolated_config(config_path: Path) -> Config:
    """A Config that bypasses the singleton and only touches config_path."""
    instance = object.__new__(Config)
    instance.init_config()
    instance._PATH_CONFIG = str(config_path)
    return instance


class WeightLicenseMetadataTests(unittest.TestCase):
    def test_every_weight_has_license_metadata(self) -> None:
        for weight_type, weight in ctranslate2_weights.items():
            with self.subTest(weight_type=weight_type):
                self.assertIn(weight.get("license"), {"MIT", "CC-BY-NC-4.0"})
                self.assertIsInstance(weight.get("commercial_use"), bool)

    def test_nllb_is_non_commercial_and_m2m100_is_mit(self) -> None:
        for weight_type, weight in ctranslate2_weights.items():
            with self.subTest(weight_type=weight_type):
                if weight_type.startswith("nllb-"):
                    self.assertEqual(weight["license"], "CC-BY-NC-4.0")
                    self.assertTrue(isNonCommercialCTranslate2Weight(weight_type))
                else:
                    self.assertTrue(weight_type.startswith("m2m100_"))
                    self.assertEqual(weight["license"], "MIT")
                    self.assertFalse(isNonCommercialCTranslate2Weight(weight_type))

    def test_default_weight_allows_commercial_use(self) -> None:
        self.assertEqual(DEFAULT_CTRANSLATE2_WEIGHT_TYPE, M2M100)
        self.assertTrue(ctranslate2_weights[DEFAULT_CTRANSLATE2_WEIGHT_TYPE]["commercial_use"])

    def test_ui_weight_list_matches_backend_licenses(self) -> None:
        """src-ui/logics/ui_configs.js repeats the license per weight for the
        Config -> Translation list; it must not drift from the backend."""
        source = UI_CONFIGS_JS.read_text(encoding="utf-8")
        block = source[source.index("export const ctranslate2_weight_type_status"):]
        block = block[:block.index("].map(")]
        rows = re.findall(r'\{ id: "([^"]+)",([^\n]*)\}', block)
        ui = {weight_id: rest for weight_id, rest in rows}
        self.assertEqual(set(ui), set(ctranslate2_weights))
        for weight_id, rest in ui.items():
            with self.subTest(weight_id=weight_id):
                expected = "...MIT" if ctranslate2_weights[weight_id]["commercial_use"] else "...CC_BY_NC_4_0"
                self.assertIn(expected, rest)
                self.assertEqual("is_default: true" in rest, weight_id == DEFAULT_CTRANSLATE2_WEIGHT_TYPE)


class ConfigDefaultAndSavedWeightTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.config_path = Path(tmpdir.name) / "config.json"

    def _load(self, saved: dict = None) -> Config:
        if saved is not None:
            self.config_path.write_text(json.dumps(saved), encoding="utf-8")
        instance = _isolated_config(self.config_path)
        instance.load_config()
        self.addCleanup(lambda: getattr(instance, "_timer", None) and instance._timer.cancel())
        return instance

    def _saved_value(self, key: str):
        return json.loads(self.config_path.read_text(encoding="utf-8")).get(key)

    def test_fresh_config_defaults_to_m2m100(self) -> None:
        instance = self._load()
        self.assertEqual(instance.CTRANSLATE2_WEIGHT_TYPE, M2M100)
        self.assertFalse(instance.CTRANSLATE2_LICENSE_NOTICE_SHOWN)
        self.assertEqual(self._saved_value("CTRANSLATE2_WEIGHT_TYPE"), M2M100)

    def test_saved_nllb_weight_is_kept(self) -> None:
        # Older versions saved their default, so this is what every existing
        # install has unless the user picked something else.
        instance = self._load({"CTRANSLATE2_WEIGHT_TYPE": NLLB_600M})
        self.assertEqual(instance.CTRANSLATE2_WEIGHT_TYPE, NLLB_600M)
        # load_config() rewrites config.json; the choice must survive that.
        self.assertEqual(self._saved_value("CTRANSLATE2_WEIGHT_TYPE"), NLLB_600M)
        self.assertFalse(instance.CTRANSLATE2_LICENSE_NOTICE_SHOWN)

    def test_saved_large_nllb_weight_and_notice_flag_are_kept(self) -> None:
        instance = self._load({"CTRANSLATE2_WEIGHT_TYPE": NLLB_1_3B, "CTRANSLATE2_LICENSE_NOTICE_SHOWN": True})
        self.assertEqual(instance.CTRANSLATE2_WEIGHT_TYPE, NLLB_1_3B)
        self.assertTrue(instance.CTRANSLATE2_LICENSE_NOTICE_SHOWN)


class _ControllerTestBase(unittest.TestCase):
    RUN_MAPPING = {
        "selected_translation_engines": "/run/selected_translation_engines",
        "translation_engines": "/run/translation_engines",
        "selected_your_languages": "/run/selected_your_languages",
        "selected_target_languages": "/run/selected_target_languages",
        "ctranslate2_license_notice": "/run/ctranslate2_license_notice",
        "translation_language_unsupported": "/run/translation_language_unsupported",
        "download_progress_ctranslate2_weight": "/run/download_progress_ctranslate2_weight",
        "downloaded_ctranslate2_weight": "/run/downloaded_ctranslate2_weight",
        "error_ctranslate2_weight": "/run/error_ctranslate2_weight",
    }

    def setUp(self) -> None:
        self.controller = Controller.__new__(Controller)
        self.controller.run_mapping = dict(self.RUN_MAPPING)
        self.pushes = []
        self.controller.run = lambda status, endpoint, result: self.pushes.append((status, endpoint, result))

        saved = {name: getattr(config, name) for name in (
            "CTRANSLATE2_WEIGHT_TYPE", "CTRANSLATE2_LICENSE_NOTICE_SHOWN", "SELECTED_TAB_NO",
            "SELECTED_TRANSLATION_ENGINES", "SELECTED_YOUR_LANGUAGES", "SELECTED_TARGET_LANGUAGES",
        )}
        saved["SELECTABLE_TRANSLATION_ENGINE_STATUS"] = dict(config.SELECTABLE_TRANSLATION_ENGINE_STATUS)

        def restore():
            for name, value in saved.items():
                setattr(config, name, value)
        self.addCleanup(restore)

        changed = patch.object(model, "setChangedTranslatorParameters")
        self.changed_parameters = changed.start()
        self.addCleanup(changed.stop)

        config.CTRANSLATE2_WEIGHT_TYPE = M2M100
        config.CTRANSLATE2_LICENSE_NOTICE_SHOWN = False

    def pushed(self, endpoint: str) -> list:
        return [push for push in self.pushes if push[1] == endpoint]


class SelectWeightRequiresOptInTests(_ControllerTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.revalidations = []
        self.controller.updateTranslationEngineAndEngineList = lambda: self.revalidations.append(config.CTRANSLATE2_WEIGHT_TYPE)

    def test_nllb_without_opt_in_is_refused(self) -> None:
        response = self.controller.setCtranslate2WeightType(NLLB_600M)
        self.assertEqual(response["status"], 400)
        self.assertEqual(response["result"]["error_code"], "WEIGHT_CTRANSLATE2_LICENSE_CONSENT_REQUIRED")
        self.assertEqual(response["result"]["data"], {"weight_type": NLLB_600M, "selected": M2M100})
        self.assertEqual(config.CTRANSLATE2_WEIGHT_TYPE, M2M100)
        self.changed_parameters.assert_not_called()

    def test_opt_in_flag_must_be_true(self) -> None:
        response = self.controller.setCtranslate2WeightType({"weight_type": NLLB_600M, "accept_non_commercial_license": "yes"})
        self.assertEqual(response["status"], 400)
        self.assertEqual(config.CTRANSLATE2_WEIGHT_TYPE, M2M100)

    def test_nllb_with_opt_in_is_selected_and_revalidated(self) -> None:
        response = self.controller.setCtranslate2WeightType({"weight_type": NLLB_1_3B, "accept_non_commercial_license": True})
        self.assertEqual(response, {"status": 200, "result": NLLB_1_3B})
        self.assertEqual(config.CTRANSLATE2_WEIGHT_TYPE, NLLB_1_3B)
        self.assertTrue(config.CTRANSLATE2_LICENSE_NOTICE_SHOWN)
        self.assertEqual(self.revalidations, [NLLB_1_3B])

    def test_mit_weight_needs_no_opt_in(self) -> None:
        response = self.controller.setCtranslate2WeightType("m2m100_1.2B-ct2-int8")
        self.assertEqual(response, {"status": 200, "result": "m2m100_1.2B-ct2-int8"})
        self.assertFalse(config.CTRANSLATE2_LICENSE_NOTICE_SHOWN)

    def test_already_selected_nllb_weight_is_accepted_without_opt_in(self) -> None:
        config.CTRANSLATE2_WEIGHT_TYPE = NLLB_600M  # saved by an older version
        response = self.controller.setCtranslate2WeightType(NLLB_600M)
        self.assertEqual(response, {"status": 200, "result": NLLB_600M})


class DownloadWeightRequiresOptInTests(_ControllerTestBase):
    def setUp(self) -> None:
        super().setUp()
        for name in ("downloadCTranslate2ModelWeight", "downloadCTranslate2ModelTokenizer"):
            patcher = patch.object(model, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_nllb_download_without_opt_in_is_refused(self) -> None:
        response = self.controller.downloadCtranslate2Weight(NLLB_600M, asynchronous=False)
        self.assertEqual(response["status"], 400)
        self.assertEqual(response["result"]["error_code"], "WEIGHT_CTRANSLATE2_LICENSE_CONSENT_REQUIRED")
        self.downloadCTranslate2ModelWeight.assert_not_called()
        self.downloadCTranslate2ModelTokenizer.assert_not_called()

    def test_nllb_download_with_opt_in_starts(self) -> None:
        response = self.controller.downloadCtranslate2Weight(
            {"weight_type": NLLB_600M, "accept_non_commercial_license": True}, asynchronous=False)
        self.assertEqual(response, {"status": 200, "result": True})
        self.assertEqual(self.downloadCTranslate2ModelWeight.call_args.args[0], NLLB_600M)
        self.downloadCTranslate2ModelTokenizer.assert_called_once_with(NLLB_600M)
        # Downloading alone does not select it.
        self.assertEqual(config.CTRANSLATE2_WEIGHT_TYPE, M2M100)

    def test_saved_nllb_weight_still_auto_downloads(self) -> None:
        # Startup auto-download passes the saved weight as a bare id.
        config.CTRANSLATE2_WEIGHT_TYPE = NLLB_600M
        response = self.controller.downloadCtranslate2Weight(NLLB_600M, asynchronous=False)
        self.assertEqual(response, {"status": 200, "result": True})
        self.downloadCTranslate2ModelWeight.assert_called_once()

    def test_default_weight_downloads_without_opt_in(self) -> None:
        response = self.controller.downloadCtranslate2Weight(M2M100, asynchronous=False)
        self.assertEqual(response, {"status": 200, "result": True})


class NonCommercialNoticeTests(_ControllerTestBase):
    def test_saved_nllb_weight_gets_one_notice(self) -> None:
        config.CTRANSLATE2_WEIGHT_TYPE = NLLB_600M
        self.controller.notifyNonCommercialCTranslate2Weight()
        self.controller.notifyNonCommercialCTranslate2Weight()

        notices = self.pushed("/run/ctranslate2_license_notice")
        self.assertEqual(len(notices), 1)
        status, _, result = notices[0]
        self.assertEqual(status, 400)
        self.assertEqual(result["error_code"], "WEIGHT_CTRANSLATE2_NON_COMMERCIAL_NOTICE")
        self.assertEqual(result["data"], {"weight_type": NLLB_600M, "license": "CC-BY-NC-4.0"})
        self.assertTrue(config.CTRANSLATE2_LICENSE_NOTICE_SHOWN)
        # The notice does not change the setting.
        self.assertEqual(config.CTRANSLATE2_WEIGHT_TYPE, NLLB_600M)

    def test_mit_weight_gets_no_notice(self) -> None:
        self.controller.notifyNonCommercialCTranslate2Weight()
        self.assertEqual(self.pushes, [])
        self.assertFalse(config.CTRANSLATE2_LICENSE_NOTICE_SHOWN)


class M2M100LanguageMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(LANGUAGES_YAML, encoding="utf-8") as fp:
            cls.languages = yaml.safe_load(fp)["CTranslate2"]

    def test_tokenizer_code_list_matches_installed_transformers(self) -> None:
        try:
            from transformers.models.m2m_100.tokenization_m2m_100 import FAIRSEQ_LANGUAGE_CODES
        except Exception:
            self.skipTest("transformers is not installed in this environment")
        self.assertEqual(set(FAIRSEQ_LANGUAGE_CODES["m2m100"]), M2M100_TOKENIZER_CODES)

    def test_every_m2m100_code_exists_in_the_tokenizer(self) -> None:
        for weight_type in ("m2m100_418M-ct2-int8", "m2m100_1.2B-ct2-int8"):
            for side in ("source", "target"):
                for language, code in self.languages[weight_type][side].items():
                    with self.subTest(weight_type=weight_type, side=side, language=language):
                        self.assertIn(code, M2M100_TOKENIZER_CODES)

    def test_code_fixes(self) -> None:
        table = self.languages[M2M100]["source"]
        self.assertEqual(table["Javanese"], "jv")
        self.assertEqual(table["Burmese"], "my")
        self.assertEqual(table["Japanese"], "ja")
        self.assertEqual(table["Filipino"], "tl")

    def test_languages_m2m100_lacks_raise_unsupported(self) -> None:
        for language in ("Basque", "Telugu"):
            with self.subTest(language=language):
                with self.assertRaises(UnsupportedLanguageError):
                    Translator.getLanguageCode("CTranslate2", M2M100, "", language, "English")
                # NLLB does have them, which is why switching weights must re-check.
                Translator.getLanguageCode("CTranslate2", NLLB_600M, "", language, "English")


class SwitchingToM2M100ResetsUnsupportedLanguageTests(_ControllerTestBase):
    TAB_NO = "1"

    def setUp(self) -> None:
        super().setUp()
        config.SELECTED_TAB_NO = self.TAB_NO
        config.SELECTABLE_TRANSLATION_ENGINE_STATUS = {
            engine: engine == "CTranslate2" for engine in config.SELECTABLE_TRANSLATION_ENGINE_STATUS
        }
        config.CTRANSLATE2_WEIGHT_TYPE = NLLB_600M
        config.SELECTED_TRANSLATION_ENGINES = {self.TAB_NO: "CTranslate2"}
        config.SELECTED_YOUR_LANGUAGES = {
            self.TAB_NO: {"1": {"language": "Basque", "country": "Spain", "enable": True}},
        }
        config.SELECTED_TARGET_LANGUAGES = {
            self.TAB_NO: {
                "1": {"language": "English", "country": "United States", "enable": True},
                "2": {"language": "Telugu", "country": "India", "enable": True},
                "3": {"language": "English", "country": "United States", "enable": False},
            },
        }

    def test_switch_resets_with_a_warning(self) -> None:
        response = self.controller.setCtranslate2WeightType(M2M100)

        self.assertEqual(response, {"status": 200, "result": M2M100})
        self.assertNotEqual(config.SELECTED_YOUR_LANGUAGES[self.TAB_NO]["1"]["language"], "Basque")
        targets = [target["language"] for target in config.SELECTED_TARGET_LANGUAGES[self.TAB_NO].values() if target["enable"]]
        self.assertNotIn("Telugu", targets)

        warnings = self.pushed("/run/translation_language_unsupported")
        self.assertEqual(len(warnings), 1)
        status, _, result = warnings[0]
        self.assertEqual(status, 400)
        self.assertEqual(result["error_code"], "TRANSLATION_LANGUAGE_UNSUPPORTED")
        self.assertEqual(result["data"], {"engine": "CTranslate2", "weight_type": M2M100, "languages": ["Basque", "Telugu"]})

    def test_supported_languages_switch_silently(self) -> None:
        config.SELECTED_YOUR_LANGUAGES = {
            self.TAB_NO: {"1": {"language": "Japanese", "country": "Japan", "enable": True}},
        }
        targets = config.SELECTED_TARGET_LANGUAGES
        targets[self.TAB_NO]["2"]["enable"] = False
        config.SELECTED_TARGET_LANGUAGES = targets

        self.controller.setCtranslate2WeightType(M2M100)

        self.assertEqual(config.SELECTED_YOUR_LANGUAGES[self.TAB_NO]["1"]["language"], "Japanese")
        self.assertEqual(self.pushed("/run/translation_language_unsupported"), [])


if __name__ == "__main__":
    unittest.main()
