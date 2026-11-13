"""Download failure correlation, without importing the runtime or starting workers."""
import ast
from pathlib import Path
from queue import Empty
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "mainloop.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
NAMESPACE = {"Any": object}
exec(compile(ast.Module(body=[next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                                 and node.name == "_request_error_result")], type_ignores=[]),
             str(SOURCE), "exec"), NAMESPACE)
error_result = NAMESPACE["_request_error_result"]
MAIN = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "Main")
HANDLER = next(node for node in MAIN.body if isinstance(node, ast.FunctionDef) and node.name == "handler")


@pytest.mark.parametrize("status", [404, 423, 500])
@pytest.mark.parametrize("endpoint", ["/run/download_ctranslate2_weight", "/run/download_whisper_weight"])
@pytest.mark.parametrize("data", ["small", {"weight_type": "small", "accept_non_commercial_license": True}])
def test_legacy_download_errors_identify_only_the_failed_weight(status, endpoint, data):
    assert error_result(endpoint, data, "Internal error", status) == {
        "message": "Internal error", "data": {"weight_type": "small"},
    }


@pytest.mark.parametrize("status", [200, 400, 409])
def test_success_and_specific_errors_keep_their_existing_contract(status):
    result = {"error_code": "WEIGHT_CTRANSLATE2_LICENSE_CONSENT_REQUIRED", "data": {"selected": "small"}}
    assert error_result("/run/download_ctranslate2_weight", "large", result, status) is result


def test_unrelated_requests_never_echo_secrets_or_messages():
    for endpoint in ["/set/data/deepl_auth_key", "/run/send_message_box", "/run/start_model_download"]:
        assert error_result(endpoint, {"secret": "not for stdout"}, "Internal error", 500) == "Internal error"


def test_invalid_weight_identifier_does_not_echo_other_fields():
    assert error_result("/run/download_whisper_weight", {"other": "secret"}, None, 500) is None


def test_every_worker_terminal_response_uses_failure_correlation():
    responses = [node for node in ast.walk(HANDLER) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "printResponse"]
    # 各分岐は共通の応答箇所に合流する。分岐からの到達は下の実行テストで確認する。
    assert len(responses) == 1
    for response in responses:
        assert isinstance(response.args[2], ast.Call)
        assert isinstance(response.args[2].func, ast.Name)
        assert response.args[2].func.id == "_request_error_result"
        assert [arg.id for arg in response.args[2].args] == ["endpoint", "data", "result", "status"]


@pytest.mark.parametrize("endpoint", ["/run/download_ctranslate2_weight", "/run/download_whisper_weight"])
@pytest.mark.parametrize("path,status,result", [
    ("busy", 423, "Locked endpoint (busy)"),
    ("initialization", 423, None),
    ("completion", 500, "Internal error"),
    ("completion", 200, {"downloaded": True}),
])
def test_terminal_branches_reach_correlated_response(endpoint, path, status, result):
    # 本物の handler 本体だけを実行し、キューと処理先はメモリ上の代役にする。
    # スレッドやソケットを起動せず、再試行ではなく終了する各分岐を通す。
    stop = Event()
    queue = Mock()
    data = {"weight_type": "small", "other": "not for stdout"}
    request = SimpleNamespace(endpoint=endpoint, data=data, attempt=3)
    lock = None if path == "busy" else object()
    queue.get_ready.return_value = (request, lock, path == "busy")
    queue.finish.side_effect = lambda *args: stop.set()
    main = SimpleNamespace(_stop_event=stop, queue=queue, _call_handler=Mock(return_value=(result, status)))
    correlate = Mock(wraps=error_result)
    respond = Mock()
    namespace = {
        "Empty": Empty, "printLog": Mock(), "printResponse": respond,
        "isQuietPoll": lambda *args: False, "_request_error_result": correlate,
        "_ENDPOINT_LOCKED_MAX_RETRIES": 3,
    }
    exec(compile(ast.Module(body=[HANDLER], type_ignores=[]), str(SOURCE), "exec"), namespace)
    namespace["handler"](main)

    correlate.assert_called_once_with(endpoint, data, result, status)
    expected = result if status == 200 else {"message": result, "data": {"weight_type": "small"}}
    respond.assert_called_once_with(status, endpoint, expected)
    queue.finish.assert_called_once_with(request, lock, False)
    if path == "busy":
        main._call_handler.assert_not_called()
    else:
        main._call_handler.assert_called_once_with(endpoint, data)
