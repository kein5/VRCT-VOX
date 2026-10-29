import json
from pathlib import Path


def test_legacy_hotkeys_survive_quick_chat_upgrade(tmp_path):
    from config import Config
    cfg = object.__new__(Config)
    cfg.init_config()
    cfg._PATH_CONFIG = str(tmp_path / 'config.json')
    legacy = dict(toggle_vrct_visibility=['Ctrl', 'J'], toggle_translation=None,
                  toggle_transcription_send=None, toggle_transcription_receive=None)
    Path(cfg._PATH_CONFIG).write_text(json.dumps({'HOTKEYS': legacy}))
    try:
        cfg.load_config()
        assert cfg.HOTKEYS == dict(legacy, open_quick_chat=None)
        cfg.HOTKEYS = dict(cfg.HOTKEYS, open_quick_chat=['Ctrl', 'Alt', 'J'])
        cfg.saveConfigToFile()
        assert json.loads(Path(cfg._PATH_CONFIG).read_text())['HOTKEYS']['open_quick_chat'] == ['Ctrl', 'Alt', 'J']
    finally:
        if getattr(cfg, '_timer', None):
            cfg._timer.cancel()
