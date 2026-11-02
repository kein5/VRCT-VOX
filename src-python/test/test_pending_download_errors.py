"""Download failure correlation, without importing the runtime or starting workers."""
import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "mainloop.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
NAMESPACE = {"Any": object}
exec(compile(ast.Module(body=[next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                                 and node.name == "_request_error_result")], type_ignores=[]),
             str(SOURCE), "exec"), NAMESPACE)
error_result = NAMESPACE["_request_error_result"]


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
    main = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "Main")
    handler = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == "handler")
    responses = [node for node in ast.walk(handler) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "printResponse"]
    assert len(responses) == 3  # busy-lock limit, initialization-lock limit, completion
    for response in responses:
        assert isinstance(response.args[2], ast.Call)
        assert response.args[2].func.id == "_request_error_result"
