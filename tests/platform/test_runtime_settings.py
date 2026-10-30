"""Persist real Config in separate processes without touching a user's config."""
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def run_config(directory, program):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src-python"),
               VRCT_CONFIG_DIR=str(directory), HF_HOME=str(directory / "hf"),
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return subprocess.run([sys.executable, "-c", program], cwd=directory.parent,
                          env=env, capture_output=True, text=True, timeout=30)


def test_config_directory_isolated_and_voice_settings_survive_restart(tmp_path):
    directory = tmp_path / "separate settings"
    initial = run_config(directory, '''
import os
from config import config
assert config.PATH_CONFIG == os.path.join(os.environ["VRCT_CONFIG_DIR"], "config.json")
assert config.AUTO_DOWNLOAD_MODELS is False
assert config.VOICE_SETTINGS["mode"] == "off"
config.VOICE_SETTINGS = {**config.VOICE_SETTINGS, "japanese_voice": "test-voice"}
config.AUTO_DOWNLOAD_MODELS = True
config.saveConfigToFile()
''')
    assert initial.returncode == 0, initial.stderr
    saved = json.loads((directory / "config.json").read_text())
    assert saved["AUTO_DOWNLOAD_MODELS"] is True
    assert saved["VOICE_SETTINGS"]["japanese_voice"] == "test-voice"
    restored = run_config(directory, '''
from config import config
assert config.AUTO_DOWNLOAD_MODELS is True
assert config.VOICE_SETTINGS["japanese_voice"] == "test-voice"
assert config.VOICE_SETTINGS["mode"] == "off"
config.AUTO_DOWNLOAD_MODELS = False
config.saveConfigToFile()
''')
    assert restored.returncode == 0, restored.stderr
    assert json.loads((directory / "config.json").read_text())["AUTO_DOWNLOAD_MODELS"] is False


def test_old_config_does_not_opt_in_to_model_downloads(tmp_path):
    directory = tmp_path / "old-config"
    directory.mkdir()
    (directory / "config.json").write_text('{"UI_LANGUAGE":"ja"}')
    result = run_config(directory, '''
import os
from config import config
assert config.PATH_CONFIG == os.path.join(os.environ["VRCT_CONFIG_DIR"], "config.json")
assert config.AUTO_DOWNLOAD_MODELS is False
assert config.UI_LANGUAGE == "ja"
''')
    assert result.returncode == 0, result.stderr


def test_diagnostics_follow_config_override_without_touching_working_directory(tmp_path):
    directory = tmp_path / "isolated logs"
    result = run_config(directory, '''
import os
from pathlib import Path
from utils import setupLogger, removeLog, errorLogging
state = Path(os.environ["VRCT_CONFIG_DIR"])
setupLogger("isolated-process", "process.log").info("isolated marker")
assert "isolated marker" in (state / "logs/process.log").read_text()
removeLog()
assert (state / "logs/process.log").read_text() == ""
try:
    raise ValueError("isolated failure")
except ValueError:
    errorLogging()
assert "isolated failure" in (state / "logs/error.log").read_text()
assert not Path("process.log").exists()
assert not Path("error.log").exists()
''')
    assert result.returncode == 0, result.stderr
