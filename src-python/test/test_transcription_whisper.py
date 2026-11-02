import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from models.builtin_model_pins import MODEL_PINS
from models.transcription import transcription_whisper


def _hub_url(repo, filename, revision=None):
    return f"https://hf.example/{repo}/resolve/{revision}/{filename}"


class TestDownloadWhisperWeight(unittest.TestCase):
    """Whisper weights come from a pinned commit, and only the files pinned
    for that repository are requested. Repositories ship different file sets
    (Systran repos have vocabulary.txt; the Zoont/deepdml large-v3-turbo
    conversions have preprocessor_config.json and vocabulary.json)."""

    def setUp(self) -> None:
        # downloadWhisperWeight always calls os_makedirs on the target path
        # before checking what to download; without this patch a real
        # directory (e.g. D:\tmp\root\weights\...) gets created on disk.
        self._makedirs_patch = patch.object(transcription_whisper, "os_makedirs")
        self._makedirs_patch.start()

    def tearDown(self) -> None:
        self._makedirs_patch.stop()

    @patch.object(transcription_whisper, "checkWhisperWeight", return_value=False)
    @patch.object(transcription_whisper, "downloadFile")
    @patch("huggingface_hub.hf_hub_url", side_effect=_hub_url)
    def test_downloads_the_pinned_files_at_the_pinned_commit(self, _hub, mock_download_file, _check) -> None:
        for weight_type in ("base", "large-v3-turbo"):
            with self.subTest(weight_type=weight_type):
                mock_download_file.reset_mock()
                pin = MODEL_PINS[transcription_whisper._MODELS[weight_type]]

                transcription_whisper.downloadWhisperWeight("/tmp/root", weight_type)

                calls = {c.args[1].split("/")[-1]: c for c in mock_download_file.call_args_list}
                self.assertEqual(set(calls), set(pin["files"]))
                for name, call in calls.items():
                    self.assertIn(f"/resolve/{pin['revision']}/{name}", call.args[0])
                    self.assertEqual(call.kwargs["pin"], pin["files"][name])

    @patch.object(transcription_whisper, "checkWhisperWeight", return_value=True)
    @patch.object(transcription_whisper, "downloadFile")
    def test_skips_download_entirely_when_weight_already_verified(self, mock_download_file, _check) -> None:
        transcription_whisper.downloadWhisperWeight("/tmp/root", "base")

        mock_download_file.assert_not_called()

    @patch.object(transcription_whisper, "checkWhisperWeight", return_value=False)
    @patch.object(transcription_whisper, "downloadFile")
    @patch("huggingface_hub.hf_hub_url", side_effect=_hub_url)
    def test_calls_end_callback_after_download(self, _hub, _download, _check) -> None:
        end_callback = MagicMock()

        transcription_whisper.downloadWhisperWeight("/tmp/root", "base", end_callback=end_callback)

        end_callback.assert_called_once()


class TestDownloadFileVerification(unittest.TestCase):
    def _response(self, body: bytes):
        res = MagicMock()
        res.headers = {"content-length": str(len(body))}
        res.iter_content.return_value = [body]
        return res

    def test_keeps_a_file_that_matches_its_pin(self) -> None:
        body = b"weights"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "model.bin"
            with patch.object(transcription_whisper, "requests_get", return_value=self._response(body)):
                ok = transcription_whisper.downloadFile("https://hf.example/x", str(target),
                                                        pin=(len(body), hashlib.sha256(body).hexdigest()))

            self.assertTrue(ok)
            self.assertEqual(target.read_bytes(), body)
            self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_rejects_a_file_that_differs_from_its_pin(self) -> None:
        # A changed upstream file must not be loaded, even with the right size.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "model.bin"
            with patch.object(transcription_whisper, "requests_get", return_value=self._response(b"tampered")), \
                 patch.object(transcription_whisper, "errorLogging"), patch.object(transcription_whisper, "sleep"), \
                 patch.object(transcription_whisper, "printLog"):
                ok = transcription_whisper.downloadFile("https://hf.example/x", str(target),
                                                        pin=(8, hashlib.sha256(b"original").hexdigest()))

            self.assertFalse(ok)
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
