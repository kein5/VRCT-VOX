"""Run the measurement harness's real status/finally flow with injected cleanup."""
import ast
import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def lifecycle(source):
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == 'test_native_osc_once_with_voice_and_ui_to_write_measurement')
    block = copy.deepcopy(next(n for n in function.body if isinstance(n, ast.Try)))
    owned = block.body[0]
    assert isinstance(owned, ast.With)
    # Replace expensive native/model work, retaining any success assignment at
    # its original indentation. Keep the actual handlers and persistence code.
    def success(node):
        return (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and node.value.value == 'passed')
    owned.items = [ast.withitem(ast.Call(ast.Name('cleanup', ast.Load()), [], []))]
    owned.body = [n for n in owned.body if success(n)] or [ast.Pass()]
    block.body = [owned] + [n for n in block.body[1:] if success(n)]
    return compile(ast.fix_missing_locations(ast.Module(body=[block], type_ignores=[])), '<native-lifecycle>', 'exec')


@pytest.mark.parametrize('broken', [False, True])
def test_report_cannot_pass_before_owned_context_cleanup(tmp_path, broken):
    class Cleanup:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            if broken:
                raise OSError('owned audio cleanup failed')
    report = {'status': 'failed'}
    source = (ROOT / 'tests/platform/test_native_voice_measurement.py').read_text()
    env = dict(cleanup=Cleanup, report=report, tmp_path=tmp_path, json=json)
    if broken:
        with pytest.raises(OSError, match='owned audio cleanup failed'):
            exec(lifecycle(source), env)
    else:
        exec(lifecycle(source), env)
    saved = json.loads((tmp_path / 'report.json').read_text())
    assert saved['status'] == ('failed' if broken else 'passed')
    if broken:
        assert saved['error_type'] == 'OSError'
