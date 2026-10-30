"""KDE/X11 shortcut -> separate input -> existing sidecar/translation/OSC/TTS.

Uses local HTTP fixtures and private PipeWire. No model, host microphone or
VRChat connection. Real IME behavior is covered only by synthetic browser events.
"""
import base64
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

import pytest

from native_webdriver import NativeWebDriver, ROOT
from native_processes import sidecars
from test_native_ui import initial_state
from test_native_realtime import TranslationFixture
from tools.voice_acceptance import private_graph, wait_for

pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_QUICK_CHAT') != '1', reason='opt-in desktop shortcut/private graph')


def xdo(*args):
    return subprocess.check_output(['xdotool', *map(str, args)], text=True, timeout=5).strip()


def window_for(pid, title):
    found = subprocess.run(['xdotool', 'search', '--all', '--onlyvisible', '--pid', str(pid), '--name', f'^{title}$'],
                           capture_output=True, text=True, timeout=5)
    return found.stdout.strip().splitlines() if found.returncode == 0 else []


def stacking_order():
    result = subprocess.check_output(['xprop', '-root', '_NET_CLIENT_LIST_STACKING'], text=True, timeout=5)
    return [int(xid, 16) for xid in re.findall(r'0x[0-9a-fA-F]+', result)]


def window_geometry(xid):
    return {name: int(value) for name, value in
            (line.split('=', 1) for line in xdo('getwindowgeometry', '--shell', xid).splitlines())}


@contextmanager
def fullscreen_foreground(output):
    """Owned GTK game stand-in: fullscreen and above ordinary windows."""
    with output.open('w') as log:
        process = subprocess.Popen(['/usr/bin/python3', '-c', '''
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk
window = Gtk.Window(title='Quick Chat foreground test')
window.add(Gtk.Label(label='Quick Chat foreground test'))
window.set_keep_above(True)
# Tauri centers a new Quick Chat on the primary monitor. A fullscreen window
# on a different output stays in KWin's active fullscreen layer even unfocused.
display = Gdk.Display.get_default()
primary = display.get_primary_monitor() or display.get_monitor(0)
monitor = next(i for i in range(display.get_n_monitors()) if display.get_monitor(i) == primary)
geometry = primary.get_geometry()
window.move(geometry.x + 80, geometry.y + 80)
window.fullscreen_on_monitor(display.get_default_screen(), monitor)
window.connect('destroy', Gtk.main_quit)
window.show_all()
window.present()
Gtk.main()
'''], env=dict(os.environ, GDK_BACKEND='x11'), stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_for(lambda: window_for(process.pid, 'Quick Chat foreground test'))
            xid, = window_for(process.pid, 'Quick Chat foreground test')
            def ready():
                state = subprocess.check_output(['xprop', '-id', xid, '_NET_WM_STATE'], text=True, timeout=5)
                return '_NET_WM_STATE_FULLSCREEN' in state and '_NET_WM_STATE_ABOVE' in state
            wait_for(ready)
            yield xid
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_shortcut_raises_input_above_fullscreen_without_restoring_main(tmp_path):
    state = initial_state(tmp_path)
    config = state / 'config.json'
    values = json.loads(config.read_text())
    values['HOTKEYS'] = dict(open_quick_chat=['Ctrl', 'Shift', 'Alt', 'F9'],
                            toggle_vrct_visibility=None, toggle_translation=None,
                            toggle_transcription_send=None, toggle_transcription_receive=None)
    config.write_text(json.dumps(values))
    with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state), 'GDK_BACKEND': 'x11'}) as ui:
        ui.wait("return document.querySelector('textarea[class*=message_box_input_area]') !== null")
        ui.open_voice_page('Hotkeys', '[data-setting-id="open_quick_chat"] input')
        ui.wait("return document.querySelector('[data-setting-id=\"open_quick_chat\"] input').value !== ''")
        ui.close_settings()
        ui.wait("window.__TAURI_INTERNALS__.invoke('plugin:global-shortcut|is_registered', {shortcut:'Ctrl+Shift+Alt+F9'}).then(value => window.__shortcutRegistered = value); return window.__shortcutRegistered === true")
        main = ui.command('GET', '/window')
        main_xid, = window_for(ui.app_process.pid, 'VRCT-VOX')
        xdo('windowminimize', main_xid)
        wait_for(lambda: not window_for(ui.app_process.pid, 'VRCT-VOX'))
        with fullscreen_foreground(tmp_path / 'foreground.log') as foreground:
            for opening in ('first', 'hidden', 'minimized', 'visible'):
                xdo('windowactivate', '--sync', foreground)
                wait_for(lambda: xdo('getwindowfocus') == foreground)
                xdo('key', '--clearmodifiers', 'ctrl+alt+shift+F9')
                wait_for(lambda: window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat'),
                         code=f'{opening}: Quick Chat was not shown')
                chat_xid, = window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat')
                game_geometry, chat_geometry = window_geometry(foreground), window_geometry(chat_xid)
                for coordinate, size in (('X', 'WIDTH'), ('Y', 'HEIGHT')):
                    assert game_geometry[coordinate] <= chat_geometry[coordinate]
                    assert chat_geometry[coordinate] + chat_geometry[size] <= game_geometry[coordinate] + game_geometry[size]
                try:
                    wait_for(lambda: xdo('getwindowfocus') == chat_xid,
                             code=f'{opening}: Quick Chat did not receive input focus')
                    wait_for(lambda: stacking_order().index(int(chat_xid)) > stacking_order().index(int(foreground)),
                             code=f'{opening}: Quick Chat remained behind the fullscreen window')
                finally:
                    (tmp_path / f'{opening}-windows.json').write_text(json.dumps(dict(
                        chat=chat_xid, foreground=foreground, stacking=stacking_order(),
                        active=subprocess.check_output(['xprop', '-root', '_NET_ACTIVE_WINDOW'], text=True),
                        chat_geometry=chat_geometry, foreground_geometry=game_geometry,
                        chat_state=subprocess.check_output(['xprop', '-id', chat_xid, '_NET_WM_STATE'], text=True),
                        foreground_state=subprocess.check_output(['xprop', '-id', foreground, '_NET_WM_STATE'], text=True),
                    ), indent=2))
                assert not window_for(ui.app_process.pid, 'VRCT-VOX'), opening
                chat, = [handle for handle in ui.command('GET', '/window/handles') if handle != main]
                ui.command('POST', '/window', {'handle': chat})
                ui.wait("return document.activeElement?.getAttribute('aria-label') === 'Message'")
                if opening == 'first':
                    ui.fill('Message', 'draft above the game')
                else:
                    assert ui.evaluate('return arguments[0].value', ui.control('Message')) == 'draft above the game'
                if opening == 'minimized':
                    continue  # Leave it visible; reactivate over the game next.
                if opening == 'hidden':
                    xdo('windowminimize', chat_xid)
                else:
                    xdo('key', 'Escape')
                wait_for(lambda: not window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat'))
        ui.command('POST', '/window', {'handle': main})
        xdo('windowactivate', '--sync', main_xid)
        ui.close_app()


def test_shortcut_focus_escape_and_single_pipeline(tmp_path):
    sys.path.insert(0, str(ROOT / 'tests/voice'))
    from ui_entry_acceptance import FixtureServer
    from pythonosc.osc_packet import OscPacket
    with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
        translation = stack.enter_context(TranslationFixture(['Quick chat translation']))
        tts = FixtureServer()
        tts.start()
        stack.callback(tts.stop)
        osc = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        osc.bind(('127.0.0.2', 0))
        osc.setblocking(False)
        state = initial_state(tmp_path)
        config = state / 'config.json'
        values = json.loads(config.read_text())
        values.update(HOTKEYS=dict(open_quick_chat=None,
                                  toggle_vrct_visibility=None, toggle_translation=None,
                                  toggle_transcription_send=None, toggle_transcription_receive=None),
                      AUTO_CLEAR_MESSAGE_BOX=True, LMSTUDIO_URL=translation.url,
                      SELECTED_TRANSLATION_ENGINES={str(tab): 'LMStudio' for tab in range(1, 6)},
                      SEND_MESSAGE_TO_VRC=True, OSC_PORT=osc.getsockname()[1],
                      VOICE_SETTINGS={'routing': 'managed', 'mode': 'original', 'japanese_url': tts.url})
        config.write_text(json.dumps(values))
        # The current shortcut plugin is X11-only. Test explicitly under KDE's
        # XWayland, without changing the desktop/session configuration.
        with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state), 'GDK_BACKEND': 'x11'}) as ui:
            ui.wait("return document.querySelector('textarea[class*=message_box_input_area]') !== null")
            ui.open_voice_page('Hotkeys', '[data-setting-id="open_quick_chat"] input')
            shortcut = ui.control('Open quick chat')
            assert ui.evaluate('return arguments[0].value', shortcut) == ''
            ui.element_command(shortcut, 'click')
            xdo('key', '--clearmodifiers', 'ctrl+alt+shift+j')
            wait_for(lambda: json.loads(config.read_text()).get('HOTKEYS', {}).get('open_quick_chat') == ['Ctrl', 'Shift', 'Alt', 'J'])
            ui.open_route_settings()
            ui.click_text('button', 'Resume voice')
            ui.close_settings()
            ui.click('[role=switch][aria-label=Translation]')
            ui.wait("return document.querySelector('[role=switch][aria-label=Translation]').getAttribute('aria-checked') === 'true'")
            if ui.evaluate("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked')") == 'false':
                ui.click('[role=switch][aria-label=TTS]')
            ui.wait("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked') === 'true'")
            main = ui.command('GET', '/window')
            before = sidecars(ui)
            assert len(before) == 1, before
            main_xid, = window_for(ui.app_process.pid, 'VRCT-VOX')
            xdo('windowminimize', main_xid)
            wait_for(lambda: not window_for(ui.app_process.pid, 'VRCT-VOX'))
            start = time.monotonic()
            xdo('key', '--clearmodifiers', 'ctrl+alt+shift+j')
            wait_for(lambda: window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat'))
            chat_xid, = window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat')
            wait_for(lambda: xdo('getwindowfocus') == chat_xid)
            latency_ms = (time.monotonic() - start) * 1000
            assert not window_for(ui.app_process.pid, 'VRCT-VOX'), 'opening the input must not restore the main window'
            handles = ui.command('GET', '/window/handles')
            chat, = [handle for handle in handles if handle != main]
            ui.command('POST', '/window', {'handle': chat})
            ui.wait("return document.activeElement?.getAttribute('aria-label') === 'Message'")
            assert ui.evaluate('return innerWidth <= 600 && innerHeight <= 240')
            ui.evaluate("window.__forbidden = null; window.__TAURI_INTERNALS__.invoke('quick_chat_take').then(() => window.__forbidden = 'allowed', error => window.__forbidden = String(error)); return true;")
            ui.wait("return window.__forbidden === 'quick_chat_forbidden'")
            ui.fill('Message', 'retained draft')
            xdo('key', 'Escape')
            wait_for(lambda: not window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat'))
            xdo('key', '--clearmodifiers', 'ctrl+alt+shift+j')
            wait_for(lambda: window_for(ui.app_process.pid, 'VRCT-VOX Quick Chat'))
            ui.wait("return document.hasFocus() && document.activeElement?.getAttribute('aria-label') === 'Message'")
            assert ui.evaluate('return arguments[0].value', ui.control('Message')) == 'retained draft'
            ui.fill('Message', 'Quick chat integration')
            xdo('key', 'Return')
            ui.wait("return document.querySelector('textarea').value === ''")
            wait_for(lambda: len(translation.requests) == 1 and len(tts.requests) == 1)
            (tmp_path / 'quick-chat.png').write_bytes(base64.b64decode(ui.command('GET', '/screenshot')))
            assert sidecars(ui) == before, 'the mini window must not spawn a second sidecar'
            messages = []
            until = time.monotonic() + 1
            while time.monotonic() < until:
                try:
                    messages.extend(t.message.params[0] for t in OscPacket(osc.recv(65536)).messages if t.message.address == '/chatbox/input')
                except BlockingIOError:
                    time.sleep(.02)
            assert len(messages) == 1 and 'Quick chat translation' in messages[0], messages
            assert len(translation.requests) == len(tts.requests) == 1
            ui.command('POST', '/window', {'handle': main})
            xdo('windowactivate', '--sync', main_xid)
            ui.wait("return document.querySelector('#log_container').innerText.includes('Quick chat translation')")
            ui.evaluate("window.__forbidden = null; window.__TAURI_INTERNALS__.invoke('quick_chat_submit', {request:{id:'spoof',message:'must not send'}}).then(() => window.__forbidden = 'allowed', error => window.__forbidden = String(error)); return true;")
            ui.wait("return window.__forbidden === 'quick_chat_forbidden'")
            ui.close_app()
        (tmp_path / 'quick-chat.json').write_text(json.dumps(dict(
            shortcut='Ctrl+Alt+Shift+J', platform='KDE/XWayland', key_to_focus_ms=latency_ms,
            main_stayed_minimized=True, sidecar_count=1, translation_count=1, osc_count=1, tts_count=1,
            real_models=False, physical_capture=False, physical_ime=False), indent=2))


@pytest.mark.skipif(not os.environ.get('VRCT_TEST_WAYLAND_APP'), reason='separate native Wayland binary required')
def test_wayland_explains_shortcut_limit_and_opens_from_button(tmp_path, monkeypatch):
    monkeypatch.setenv('VRCT_TEST_APP', os.environ['VRCT_TEST_WAYLAND_APP'])
    monkeypatch.delenv('VRCT_TEST_APPIMAGE', raising=False)
    state = initial_state(tmp_path)
    with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state), 'GDK_BACKEND': 'wayland'}) as ui:
        ui.wait("return document.querySelector('textarea[class*=message_box_input_area]') !== null")
        main = ui.command('GET', '/window')
        ui.open_voice_page('Hotkeys', '[data-setting-id="open_quick_chat"] input')
        ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent.includes('unavailable in native Wayland'))")
        ui.click_text('button', 'Open input window')
        ui.wait("return document.querySelector('[class*=show_main]') !== null")
        chat, = [handle for handle in ui.command('GET', '/window/handles') if handle != main]
        ui.command('POST', '/window', {'handle': chat})
        ui.wait("return document.activeElement?.getAttribute('aria-label') === 'Message'")
        ui.fill('Message', 'Wayland draft')
        ui.element_command(ui.control('Message'), 'value', {'text': '\ue004'})
        ui.wait("return document.activeElement?.tagName === 'BUTTON'")
        ui.element_command(ui.evaluate('return document.activeElement'), 'value', {'text': '\ue00c'})
        ui.command('POST', '/window', {'handle': main})
        ui.close_app()
