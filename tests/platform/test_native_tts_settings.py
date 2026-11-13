"""Model-free acceptance of split settings in the actual native application."""
import base64
import json
import os

import pytest

from native_webdriver import NativeWebDriver
from test_native_ui import initial_state

pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_GUI') != '1', reason='opt-in native desktop')


@pytest.mark.parametrize('scaling', [100, 150])
def test_split_settings_small_window_keyboard_and_long_paths(tmp_path, scaling):
    state = initial_state(tmp_path)
    config = state / 'config.json'
    config.write_text(json.dumps(dict(json.loads(config.read_text()), UI_SCALING=scaling,
                                     MESSAGE_BOX_RATIO=30, SEND_MESSAGE_BUTTON_TYPE='hide')))
    with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state)}) as ui:
        ui.wait("return document.querySelector('textarea[class*=message_box_input_area]') !== null")
        ui.command('POST', '/window/rect', {'width': 870, 'height': 654})
        ui.wait("return innerWidth === 870 && innerHeight === 654")
        assert ui.evaluate("return [...document.querySelectorAll('[role=switch]')].map(e => e.getAttribute('aria-label')).slice(-2)") == ['TTS', 'RVC']
        assert ui.evaluate("return document.querySelector('[class*=message_send_button]') === null")
        assert ui.evaluate("return [...document.querySelectorAll('[role=switch]')].slice(-2).every(e => e.getAttribute('aria-checked') === 'false')")
        ui.open_voice_settings()
        ui.select('Seed mode', 'fixed')
        seed = ui.control('Seed value')
        ui.element_command(seed, 'click')
        ui.element_command(seed, 'value', {'text': '\ue004'})  # Native Tab.
        assert ui.evaluate("return document.activeElement.getAttribute('aria-label')") == 'Instruction'
        ui.fill('Instruction', '改行を含む\n保存の試験')
        ui.click_text('button', 'Save changes')
        ui.wait("return [...document.querySelectorAll('button')].some(e => e.textContent === 'Save changes' && e.disabled)")
        ui.open_rvc_settings()
        model = '/private/' + 'permitted-long-folder/' * 15 + 'voice.pth'
        ui.fill('Permitted RVC model (.pth)', model)
        assert ui.evaluate('return arguments[0].value', ui.control('Permitted RVC model (.pth)')) == model
        ui.click_text('button', 'Save changes')
        ui.wait("return [...document.querySelectorAll('button')].some(e => e.textContent === 'Save changes' && e.disabled)")
        report = ui.evaluate('''
            const form = document.querySelector('[data-setting-id=rvc_settings]');
            return [...form.querySelectorAll('input,select,button')].map(e => {
                const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                return {name:e.getAttribute('aria-label') || e.parentElement.textContent.trim().slice(0,80),
                        left:r.left, right:r.right, height:r.height, color:s.color, background:s.backgroundColor};
            });
        ''')
        assert all(0 <= row['left'] < row['right'] <= 870 and row['height'] >= 24 for row in report), report
        (tmp_path / 'controls.json').write_text(json.dumps(report, indent=2))
        ui.assert_rendered()
        (tmp_path / 'rvc.png').write_bytes(base64.b64decode(ui.command('GET', '/screenshot')))
        ui.close_settings()
        ui.open_voice_settings()
        assert ui.evaluate('return arguments[0].value', ui.control('Instruction')) == '改行を含む\n保存の試験'
        assert ui.evaluate('return arguments[0].value', ui.control('Seed value')) == '0'
        ui.close_app()
    saved = json.loads(config.read_text())
    assert saved['MESSAGE_BOX_RATIO'] == 30
    assert saved['SEND_MESSAGE_BUTTON_TYPE'] == 'hide'
    assert saved['DIRECT_VOICE_SETTINGS']['rvc_model'] == model
