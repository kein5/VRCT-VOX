"""Regression tests for the 2026-10-31 pre-release security audit findings."""
import os
from http.client import HTTPConnection
from unittest.mock import patch

import pytest
import speech_recognition as sr

import utils
from models.obs.obs_browser_source_server import ObsBrowserSourceServer, _is_trusted_host_header
import models.transcription.transcription_providers  # noqa: F401  (applies the HTTPS upgrade)


class _Stop(Exception):
    pass


def test_google_speech_recognition_never_uses_plain_http():
    seen = []

    def capture(request, timeout=None):
        seen.append(request.full_url)
        raise _Stop()

    audio = sr.AudioData(b"\0\0" * 1600, 16000, 2)
    with patch.object(sr, "urlopen", capture):
        with pytest.raises(_Stop):
            sr.Recognizer().recognize_google(audio, language="ja-JP")
    assert seen and seen[0].startswith("https://www.google.com/speech-api/v2/recognize?")


@pytest.mark.parametrize("endpoint", [
    "/run/send_message_box", "/run/transcription_send_mic_message",
    "/run/transcription_receive_speaker_message", "/run/transcription_ocr_message",
])
def test_conversation_text_stays_out_of_the_diagnostic_log(endpoint):
    secret = "ごきげんようみなさん"
    payload = {"id": "42", "original": {"message": secret, "transliteration": []},
               "translations": [{"message": "Good day, everyone"}]}
    with patch.object(utils, "process_logger") as logger, patch.object(utils, "_enqueueLogLine"):
        utils.printLog(endpoint, {"send_data": payload})
        utils.printResponse(200, endpoint, payload)
    logged = repr([call.args for call in logger.info.call_args_list])
    assert secret not in logged and "Good day" not in logged
    assert "'42'" in logged  # Identifiers stay for diagnosis.


@pytest.mark.parametrize("host,trusted", [
    ("127.0.0.1:8080", True), ("localhost:8080", True), ("[::1]:8080", True),
    ("192.168.1.20:8080", True), ("LOCALHOST", True),
    ("attacker.example:8080", False), ("127.0.0.1.nip.io:8080", False), ("", False), (None, False),
])
def test_obs_overlay_host_header_rejects_rebound_domain_names(host, trusted):
    assert _is_trusted_host_header(host) is trusted


def test_obs_overlay_does_not_serve_its_token_to_a_rebound_domain():
    server = ObsBrowserSourceServer("127.0.0.1", 0, ws_token="secret-token")
    server.start()
    try:
        port = server._server.server_address[1]
        for host, status in (("attacker.example", 403), (f"127.0.0.1:{port}", 200)):
            connection = HTTPConnection("127.0.0.1", port, timeout=5)
            connection.putrequest("GET", "/", skip_host=True)
            connection.putheader("Host", host)
            connection.endheaders()
            response = connection.getresponse()
            body = response.read()
            connection.close()
            assert response.status == status
            assert (b"secret-token" in body) is (status == 200)
    finally:
        server.stop()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_config_file_with_api_keys_is_owner_only(tmp_path, monkeypatch):
    from config import config
    path = tmp_path / "config.json"
    path.write_text("{}")
    path.chmod(0o644)
    monkeypatch.setattr(type(config), "PATH_CONFIG", str(path))
    config.saveConfigToFile()
    assert (path.stat().st_mode & 0o777) == 0o600
