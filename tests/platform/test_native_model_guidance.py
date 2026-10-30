"""Native GPU detection, compact choices, cached verification/Apply and load.

Files are hardlinked from independently verified full HF downloads before launch.
This tests real cache verification, not a second network transfer.
"""
import json
import os
from pathlib import Path

import pytest

from native_webdriver import NativeWebDriver, ROOT
from test_native_ui import initial_state
from models.model_downloads.catalog import CATALOG
from tools.voice_acceptance import private_graph, nodes, wait_for

pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_MODEL_GUIDANCE') != '1',
                               reason='native GPU query, preverified downloads and AppImage required')


def server_field(ui, profile):
    return ui.evaluate("return [...document.querySelectorAll('section[aria-label=\"Bundled speech.cpp servers\"] fieldset')].find(e => e.querySelector('legend')?.textContent === arguments[0])", profile)


def control(ui, profile, label):
    return ui.evaluate("return [...arguments[0].querySelectorAll('label')].find(e => e.firstChild?.textContent.trim() === arguments[1])?.querySelector('input,select')", server_field(ui, profile), label)


def button(ui, profile, text):
    element = ui.evaluate("return [...arguments[0].querySelectorAll('button')].find(e => e.textContent === arguments[1])", server_field(ui, profile), text)
    ui.element_command(element, 'click')


def test_native_gpu_choices_apply_and_owned_server_lifecycle(tmp_path):
    downloads = json.loads(Path(os.environ['VRCT_TEST_VARIANT_DOWNLOAD_REPORT']).read_text())
    assert downloads['status'] == 'passed'
    state = initial_state(tmp_path)
    config = state / 'config.json'
    choices = [('Japanese TTS', 'japanese', 'irodori-v41-q8'),
               ('Multilingual TTS', 'multilingual', 'qwen3-06b-q5')]
    paths = {}
    for _, target, model_id in choices:
        entry = next(e for e in CATALOG if e.id == model_id)
        destination = state / 'downloaded_models' / model_id / entry.revision
        destination.mkdir(parents=True)
        path = destination / entry.artifacts[0].filename
        os.link(downloads['jobs'][model_id]['paths']['model'], path)
        paths[target] = str(path)
    report = dict(status='failed', native_gui=True, native_gpu_probe=True,
                  network_transfer=False, preverified_hf_cache=True, cases=[])
    try:
        with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'):
            with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()
                # The validation notice also names this GPU. Require the actual
                # device row, not merely that historical validation text.
                ui.wait("return document.body.innerText.includes('Vulkan0: NVIDIA GeForce RTX 4080 SUPER')", timeout=20)
                report['hardware_view'] = ui.evaluate("return [...document.querySelectorAll('section[aria-label=\"Download a default model\"]')].map(e => e.innerText)")
                for profile, target, model_id in choices:
                    select = control(ui, profile, 'Model variant')
                    assert select
                    options = ui.evaluate('return [...arguments[0].options].map(o => o.value)', select)
                    assert len(options) == 2 and model_id in options
                    option = ui.evaluate('return [...arguments[0].options].find(o => o.value === arguments[1])', select, model_id)
                    ui.element_command(option, 'click')
                    before = json.loads(config.read_text())['SPEECH_SERVER_SETTINGS']['profiles'][target]
                    button(ui, profile, 'Review download')
                    ui.wait("return document.querySelector('dialog[open]') !== null")
                    warning = ui.evaluate("return document.querySelector('dialog[open]').innerText")
                    assert Path(paths[target]).name in warning
                    assert not ui.evaluate("return document.querySelector('dialog[open] input[type=checkbox]').checked")
                    ui.click('dialog[open] input[type=checkbox]')
                    ui.click_text('button', 'Agree and download')
                    ui.wait("return [...document.querySelectorAll('fieldset')].some(e => e.querySelector('legend')?.textContent === " + json.dumps(profile) + " && e.innerText.includes('Downloaded and verified.'))", timeout=30)
                    assert json.loads(config.read_text())['SPEECH_SERVER_SETTINGS']['profiles'][target] == before
                    button(ui, profile, 'Apply model path')
                    wait_for(lambda: json.loads(config.read_text())['SPEECH_SERVER_SETTINGS']['profiles'][target]['model'] == paths[target])
                    assert ui.evaluate('return arguments[0].value', control(ui, profile, 'Model GGUF path')) == paths[target]
                    after = json.loads(config.read_text())['SPEECH_SERVER_SETTINGS']['profiles'][target]
                    assert {k:v for k,v in after.items() if k!='model'} == {k:v for k,v in before.items() if k!='model'}
                    button(ui, profile, 'Start server')
                    ui.wait("return [...document.querySelectorAll('fieldset')].some(e => e.querySelector('legend')?.textContent === " + json.dumps(profile) + " && [...e.querySelectorAll('[role=status]')].some(s => s.textContent === 'Ready'))", timeout=120)
                    button(ui, profile, 'Stop server')
                    ui.wait("return [...document.querySelectorAll('fieldset')].some(e => e.querySelector('legend')?.textContent === " + json.dumps(profile) + " && [...e.querySelectorAll('[role=status]')].some(s => s.textContent === 'Stopped'))", timeout=15)
                    report['cases'].append(dict(model_id=model_id, chosen_options=options, warning=warning, before=before, after=after, owned_load_stop=True))
                assert not any(n.startswith('vrct.asr.capture.') for n in nodes())
                ui.assert_rendered()
                ui.close_app()
            with NativeWebDriver(tmp_path / 'restart', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()
                for profile, target, _ in choices:
                    assert ui.evaluate('return arguments[0].value', control(ui, profile, 'Model GGUF path')) == paths[target]
                assert not ui.evaluate("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Ready')")
                ui.close_app()
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        (tmp_path / 'report.json').write_text(json.dumps(report, indent=2))
