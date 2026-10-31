"""Explicit PP-OCR model paths from consented downloads; RapidOCR never downloads."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from models.model_downloads.catalog import Artifact, Model
from models.ocr import ocr_engine_rapidocr as engine
from models.ocr import ocr_models
from models.ocr.ocr_languages import BASE_MODEL_ID, resolveModelSpec
from models.ocr.ocr_models import OcrModelFiles, OcrModelsInvalid, OcrModelsMissing, missingModels, resolveModelFiles

YML = 'Global:\n  model_name: test\nPostProcess:\n  name: CTCLabelDecode\n  character_dict:\n  - a\n  - "\'"\n  - " "\n  - 日\n'


def _entry(model_id, files, roles):
    artifacts = tuple(Artifact(name, len(body), hashlib.sha256(body).hexdigest(), role)
                      for (name, body), role in zip(files.items(), roles))
    return Model(model_id, "ocr", model_id, "Test", "Org/x", "e" * 40, "Apache-2.0", ("x",), "ppocr", artifacts)


class _Root(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.root, True)
        base = _entry(BASE_MODEL_ID, {"det.onnx": b"det", "rec.onnx": b"rec", "rec.yml": YML.encode()},
                      ("det", "rec", "dict"))
        korean = _entry("ppocrv5-korean", {"rec.onnx": b"ko-rec", "rec.yml": YML.encode()}, ("rec", "dict"))
        self.entries = {m.id: m for m in (base, korean)}
        patcher = patch.object(ocr_models, "_ENTRIES", self.entries)
        patcher.start()
        self.addCleanup(patcher.stop)
        ocr_models._verified.clear()

    def install(self, model_id, corrupt=None):
        entry = self.entries[model_id]
        directory = self.root / entry.id / entry.revision
        directory.mkdir(parents=True)
        bodies = {"det.onnx": b"det", "rec.onnx": b"rec" if model_id == BASE_MODEL_ID else b"ko-rec",
                  "rec.yml": YML.encode()}
        for artifact in entry.artifacts:
            body = bodies[artifact.filename]
            if artifact.filename == corrupt:
                body = b"X" * len(body)
            (directory / artifact.filename).write_bytes(body)
        return directory


class TestResolve(_Root):
    def test_nothing_downloaded(self) -> None:
        spec = resolveModelSpec("auto")
        self.assertEqual(missingModels(self.root, spec), [BASE_MODEL_ID])
        with self.assertRaises(OcrModelsMissing) as ctx:
            resolveModelFiles(self.root, spec)
        self.assertEqual(ctx.exception.model_ids, (BASE_MODEL_ID,))
        with self.assertRaises(OcrModelsMissing):
            resolveModelFiles(None, spec)

    def test_base_download_gives_det_rec_and_derived_keys(self) -> None:
        directory = self.install(BASE_MODEL_ID)
        files = resolveModelFiles(self.root, resolveModelSpec("auto"))
        self.assertEqual(files.det, str(directory / "det.onnx"))
        self.assertEqual(files.rec, str(directory / "rec.onnx"))
        keys = Path(files.keys)
        self.assertEqual(keys.parent, self.root / ocr_models.KEYS_DIRECTORY)
        self.assertEqual(keys.read_text(encoding="utf-8").split("\n"), ["a", "'", " ", "日", ""])

    def test_script_languages_need_the_base_detector_too(self) -> None:
        spec = resolveModelSpec("Korean")
        self.install("ppocrv5-korean")
        self.assertEqual(missingModels(self.root, spec), [BASE_MODEL_ID])
        base = self.install(BASE_MODEL_ID)
        files = resolveModelFiles(self.root, spec)
        self.assertEqual(files.det, str(base / "det.onnx"))
        self.assertTrue(files.rec.endswith("ppocrv5-korean/" + "e" * 40 + "/rec.onnx"))

    def test_tampered_file_is_rejected(self) -> None:
        self.install(BASE_MODEL_ID, corrupt="rec.onnx")
        with self.assertRaises(OcrModelsInvalid):
            resolveModelFiles(self.root, resolveModelSpec("auto"))

    def test_wrong_size_counts_as_not_downloaded(self) -> None:
        directory = self.install(BASE_MODEL_ID)
        (directory / "det.onnx").write_bytes(b"de")
        self.assertEqual(missingModels(self.root, resolveModelSpec("auto")), [BASE_MODEL_ID])

    def test_symlinked_model_is_not_trusted(self) -> None:
        directory = self.install(BASE_MODEL_ID)
        outside = self.root / "outside.onnx"
        outside.write_bytes(b"det")
        (directory / "det.onnx").unlink()
        (directory / "det.onnx").symlink_to(outside)
        self.assertEqual(missingModels(self.root, resolveModelSpec("auto")), [BASE_MODEL_ID])

    def test_dictionary_without_characters_is_invalid(self) -> None:
        bad = b"PostProcess: {}\n"
        self.entries[BASE_MODEL_ID] = _entry(BASE_MODEL_ID, {"det.onnx": b"det", "rec.onnx": b"rec", "rec.yml": bad},
                                             ("det", "rec", "dict"))
        directory = self.root / BASE_MODEL_ID / ("e" * 40)
        directory.mkdir(parents=True)
        for name, body in (("det.onnx", b"det"), ("rec.onnx", b"rec"), ("rec.yml", bad)):
            (directory / name).write_bytes(body)
        with self.assertRaises(OcrModelsInvalid):
            resolveModelFiles(self.root, resolveModelSpec("auto"))

    def test_every_language_maps_to_catalog_entries(self) -> None:
        from models.model_downloads.catalog import CATALOG
        from models.ocr.ocr_languages import SELECTABLE_LANGUAGES
        ids = {m.id for m in CATALOG if m.target == "ocr"}
        for language in SELECTABLE_LANGUAGES:
            spec = resolveModelSpec(language)
            self.assertTrue(set(spec.model_ids) <= ids, language)
            self.assertEqual(spec.model_ids[0], BASE_MODEL_ID)


class TestEngineGetsExplicitPaths(unittest.TestCase):
    def setUp(self) -> None:
        engine._engine_cache.clear()
        self.addCleanup(engine._engine_cache.clear)

    def test_no_files_no_reader(self) -> None:
        with patch.object(engine, "RapidOCR") as rapid:
            self.assertIsNone(engine.getReader(resolveModelSpec("auto"), None))
        rapid.assert_not_called()

    def test_every_model_rapidocr_would_fetch_has_a_path(self) -> None:
        files = OcrModelFiles(det="/m/det.onnx", rec="/m/rec.onnx", keys="/m/keys.txt")
        with patch.object(engine, "RapidOCR") as rapid:
            reader = engine.getReader(resolveModelSpec("Korean"), files)
        self.assertIs(reader, rapid.return_value)
        params = rapid.call_args.kwargs["params"]
        self.assertEqual(params["Det.model_path"], "/m/det.onnx")
        self.assertEqual(params["Rec.model_path"], "/m/rec.onnx")
        self.assertEqual(params["Rec.rec_keys_path"], "/m/keys.txt")
        # The classifier is disabled but RapidOCR 3.9.2 still opens it: never without a path.
        self.assertEqual(params["Cls.model_path"], "/m/det.onnx")
        self.assertIs(params["Global.use_cls"], False)

    @unittest.skipUnless(engine.RapidOCR is not None, "rapidocr not installed")
    def test_rapidocr_downloader_is_blocked(self) -> None:
        from rapidocr.utils.download_file import DownloadFile, DownloadFileInput
        with tempfile.TemporaryDirectory() as directory, patch("requests.get") as get, \
                patch("requests.Session.get") as session_get:
            with self.assertRaises(engine.ImplicitDownloadBlocked):
                DownloadFile.run(DownloadFileInput(file_url="https://example.invalid/x.onnx",
                                                   save_path=Path(directory) / "x.onnx", logger=None))
        get.assert_not_called()
        session_get.assert_not_called()

    @unittest.skipUnless(engine.RapidOCR is not None, "rapidocr not installed")
    def test_missing_model_file_fails_without_network(self) -> None:
        files = OcrModelFiles(det="/nonexistent/det.onnx", rec="/nonexistent/rec.onnx", keys="/nonexistent/k.txt")
        with patch("requests.get") as get, patch.object(engine, "errorLogging"), patch.object(engine, "printLog"):
            self.assertIsNone(engine.getReader(resolveModelSpec("auto"), files))
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
