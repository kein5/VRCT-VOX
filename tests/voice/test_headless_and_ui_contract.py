import ast
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_headless_cli_does_not_import_windows_or_heavy_model_runtime():
    code = """
import runpy, sys
sys.argv = ['voice_cli.py', '--help']
try:
    runpy.run_path('tools/voice_cli.py', run_name='__main__')
except SystemExit as exc:
    assert exc.code == 0
for name in ('pyaudiowpatch', 'pycaw', 'windows_capture', 'model', 'config', 'torch', 'numpy'):
    assert name not in sys.modules, name
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert "speak" in result.stdout


def test_voice_endpoints_exist_on_both_sides():
    tree = ast.parse((ROOT / "src-python/mainloop.py").read_text(encoding="utf-8"))
    backend = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and ("/voice_" in n.value or n.value == "/run/stop_voice")}
    routes = (ROOT / "src-ui/logics/useReceiveRoutes.js").read_text(encoding="utf-8")
    frontend = set(re.findall(r'endpoint: "([^"]*(?:/voice_[^"/]+|/stop_voice))"', routes))
    assert backend == frontend
    assert len(backend) == 5


def test_ui_labels_have_japanese_and_english_translations():
    import yaml
    en = yaml.safe_load((ROOT / "locales/en.yml").read_text(encoding="utf-8"))["voice"]
    ja = yaml.safe_load((ROOT / "locales/ja.yml").read_text(encoding="utf-8"))["voice"]
    assert set(en) == set(ja)
    assert all(en.values()) and all(ja.values())
