"""Opt-in native consent, real HF RVC transfer, Apply and restart persistence."""
import hashlib
import json
import os

import pytest

from native_webdriver import NativeWebDriver, ROOT
from test_native_ui import initial_state
from models.model_downloads.catalog import CATALOG
from tools.voice_acceptance import private_graph, nodes, wait_for

pytestmark = pytest.mark.skipif(
    os.environ.get('VRCT_TEST_NATIVE_MODEL_DOWNLOADS') != '1',
    reason='explicit native GUI and 336 MB HF transfer opt-in required')


def test_native_download_consent_apply_and_restart(tmp_path):
    report = dict(status='failed', native_gui=True, real_network=True,
                  tts_downloaded=False, model_loaded=False, physical_audio=False)
    state = initial_state(tmp_path)
    config = state / 'config.json'
    entry = next(e for e in CATALOG if e.id == 'rvc-saisho')
    try:
        with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'):
            with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()
                # Both TTS cards must be visible and independently require consent.
                for model in ('Irodori', 'Qwen'):
                    button = ui.wait("return [...document.querySelectorAll('section[aria-label=\"Download a default model\"] > div')].find(e => e.querySelector('strong')?.textContent.includes(" + json.dumps(model) + "))?.querySelector('button')")
                    ui.element_command(button, 'click')
                    ui.wait("return document.querySelector('dialog[open]') !== null")
                    assert ui.evaluate("return document.querySelector('dialog[open] input[type=checkbox]').checked") is False
                    assert ui.evaluate("return [...document.querySelectorAll('dialog[open] button')].find(e => e.textContent === 'Agree and download').disabled")
                    body = ui.evaluate("return document.querySelector('dialog[open]').innerText")
                    assert 'Save to' in body and 'Hugging Face' in body
                    report[model + '_warning'] = body
                    ui.click_text('button', 'Back')
                assert not (state / 'downloaded_models').exists(), 'review alone downloaded files'
                ui.open_rvc_settings()
                before = json.loads(config.read_text())['DIRECT_VOICE_SETTINGS']
                ui.click_text('button', 'Review download')
                ui.wait("return document.querySelector('dialog[open]') !== null")
                warning = ui.evaluate("return document.querySelector('dialog[open]').innerText")
                assert all(s in warning for s in ('335,643,277', 'Saisho', 'CC BY 4.0', 'HuBERT', 'RMVPE'))
                report['rvc_warning'] = warning
                ui.click('dialog[open] input[type=checkbox]')
                ui.click_text('button', 'Agree and download')
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Downloaded and verified.')", timeout=300)
                assert json.loads(config.read_text())['DIRECT_VOICE_SETTINGS'] == before
                destination = state / 'downloaded_models' / entry.id / entry.revision
                report['files'] = []
                for artifact in entry.artifacts:
                    path = destination / artifact.filename
                    with path.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    assert path.stat().st_size == artifact.size and digest == artifact.sha256
                    report['files'].append(dict(path=str(path), size=artifact.size, sha256=digest))
                ui.click_text('button', 'Apply model path')
                wait_for(lambda: json.loads(config.read_text())['DIRECT_VOICE_SETTINGS']['rvc_model'] == str(destination / 'model.pth'))
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Model path applied.')")
                assert ui.evaluate('return arguments[0].value', ui.control('Permitted RVC model (.pth)')) == str(destination / 'model.pth')
                after = json.loads(config.read_text())['DIRECT_VOICE_SETTINGS']
                assert {k:v for k,v in after.items() if k not in ('rvc_model', 'rvc_index')} == {k:v for k,v in before.items() if k not in ('rvc_model', 'rvc_index')}
                assert not any(n.startswith('vrct.asr.capture.') for n in nodes())
                ui.assert_rendered()
                ui.close_app()
            with NativeWebDriver(tmp_path / 'restart', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_rvc_settings()
                assert ui.evaluate('return arguments[0].value', ui.control('Permitted RVC model (.pth)')) == str(destination / 'model.pth')
                assert ui.evaluate('return arguments[0].value', ui.control('Input to forward')) == ''
                assert not any(n.startswith('vrct.asr.capture.') for n in nodes())
                ui.close_app()
            report.update(settings_before=before, settings_after=after,
                          restart_preserved=True, input_remained_stopped=True)
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        (tmp_path / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
