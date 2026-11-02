"""The built-in models are fetched from pinned commits and checked against pinned hashes."""

import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from models.builtin_model_pins import MODEL_PINS, TOKENIZER_REVISIONS, verifyPinnedFile
from models.transcription import transcription_whisper
from models.translation import translation_utils

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PinTableTests(unittest.TestCase):
    def test_every_downloadable_model_and_tokenizer_is_pinned(self) -> None:
        repos = [w["hf_repo"] for w in translation_utils.ctranslate2_weights.values()]
        repos += list(transcription_whisper._MODELS.values())
        for repo in repos:
            with self.subTest(repo=repo):
                pin = MODEL_PINS[repo]
                self.assertRegex(pin["revision"], _COMMIT)
                self.assertIn("model.bin", pin["files"])
                for size, sha256 in pin["files"].values():
                    self.assertGreater(size, 0)
                    self.assertRegex(sha256, _SHA256)
        for weight in translation_utils.ctranslate2_weights.values():
            self.assertRegex(TOKENIZER_REVISIONS[weight["tokenizer"]], _COMMIT)

    def test_verify_checks_size_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f"
            path.write_bytes(b"abc")
            digest = hashlib.sha256(b"abc").hexdigest()
            self.assertTrue(verifyPinnedFile(str(path), 3, digest))
            self.assertFalse(verifyPinnedFile(str(path), 4, digest))
            self.assertFalse(verifyPinnedFile(str(path), 3, "0" * 64))
            self.assertFalse(verifyPinnedFile(str(Path(tmp) / "missing"), 3, digest))


class CTranslate2DownloadTests(unittest.TestCase):
    def test_downloads_pinned_files_and_rejects_a_changed_one(self) -> None:
        repo = translation_utils.ctranslate2_weights["m2m100_418M-ct2-int8"]["hf_repo"]
        good = b"config"
        pin = {"revision": "a" * 40, "files": {
            "config.json": (len(good), hashlib.sha256(good).hexdigest()),
            "model.bin": (4, hashlib.sha256(b"real").hexdigest()),
        }}
        bodies = {"config.json": good, "model.bin": b"fake"}

        def fake_get(url, **kwargs):
            res = MagicMock()
            body = bodies[url.rsplit("/", 1)[-1]]
            res.headers = {"content-length": str(len(body))}
            res.iter_content.return_value = [body]
            return res

        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(translation_utils.MODEL_PINS, {repo: pin}), \
             patch.object(translation_utils, "checkCTranslate2Weight", return_value=False), \
             patch.object(translation_utils, "hf_hub_url",
                          side_effect=lambda r, f, revision=None: f"https://hf.example/{r}/resolve/{revision}/{f}"), \
             patch.object(translation_utils, "requests_get", side_effect=fake_get) as get, \
             patch.object(translation_utils, "errorLogging"), patch.object(translation_utils, "sleep"), \
             patch.object(translation_utils, "printLog"):
            ok = translation_utils.downloadCTranslate2Weight(tmp, "m2m100_418M-ct2-int8")
            folder = Path(tmp) / "weights" / "ctranslate2" / "m2m100_418M-ct2-int8"
            kept = sorted(p.name for p in folder.iterdir())

        self.assertFalse(ok)
        self.assertEqual(kept, ["config.json"])  # the changed model.bin is not kept
        self.assertTrue(all(f"/resolve/{'a' * 40}/" in c.args[0] for c in get.call_args_list))


if __name__ == "__main__":
    unittest.main()
