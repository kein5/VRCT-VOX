"""Test-only sidecar: production Main/Controller/voice stack, injected services.

Not a Linux application launcher. Does not run Controller.init or import the
Windows/model runtime. Inactive services fail rather than silently succeeding.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
from threading import Lock
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src-python'), str(Path(__file__).parent)]


def main():
    import pytest
    from test_controller_integration import controller_module
    from models.osc.osc import OSCHandler
    from tools.live_tts_acceptance import PCMTap

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--osc-port', type=int, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    os.chdir(args.output)
    lock = Lock()

    def journal(kind, **values):
        with lock, (args.output / 'services.jsonl').open('a') as f:
            f.write(json.dumps({'kind': kind, 'time_ns': time.monotonic_ns(), **values}) + '\n')

    def wait_release(label):
        journal('blocked', label=label)
        deadline = time.monotonic() + 15
        while not (args.output / 'release').exists():
            if time.monotonic() > deadline:
                raise TimeoutError('fixture_release_missing')
            time.sleep(.01)

    osc = OSCHandler('127.0.0.1', args.osc_port)

    class Services:
        def checkKeywords(self, message):
            return False

        def checkWebSocketServerAlive(self):
            return True

        def websocketSendMessage(self, payload):
            journal('websocket_contract', payload=payload)

        def addTranslationHistory(self, source, text):
            journal('history_contract', source=source, text=text)

        def oscSendMessage(self, message):
            osc.sendMessage(message, notification=False)

        def oscStartSendTyping(self):
            osc.sendTyping(True)

        def oscStopSendTyping(self):
            osc.sendTyping(False)

        def getInputTranslate(self, message, **kwargs):
            wait_release('translation')
            return ['Hello, translated fixture.', 'こんにちは。翻訳の接続テストです。'], [True, True]

    patches = pytest.MonkeyPatch()
    controller = controller_module.__wrapped__(patches, args.output)
    controller.model = Services()
    config = controller.config
    config.SEND_MESSAGE_FORMAT_PARTS = {
        'message': {'prefix': '', 'suffix': ''},
        'translation': {'prefix': '(', 'suffix': ')', 'separator': ' / '},
        'translation_first': False, 'separator': ' ',
    }
    patches.setitem(sys.modules, 'controller', controller)
    spec = importlib.util.spec_from_file_location('entry_mainloop', ROOT / 'src-python/mainloop.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = module.main_instance
    tap = PCMTap(args.output)

    def provider(url):
        delegate = tap.provider(url)

        class ObservedProvider:
            def synthesize_stream(self, text, voice, language, token):
                journal('inference_request', text=text, language=language)
                yield from delegate.synthesize_stream(text, voice, language, token)
        return ObservedProvider()

    app.controller.voice_events.provider_factory = provider
    # Constructor-owned bus/router and all control/dispatch methods remain real.
    allowed = {'/run/send_message_box', '/run/typing_message_box', '/run/stop_typing_message_box',
               '/set/data/voice_settings', '/get/data/voice_settings', '/get/data/voice_status',
               '/get/data/voice_output_devices', '/get/data/voice_route',
               '/run/stop_voice', '/run/mute_voice', '/run/resume_voice'}
    for endpoint, entry in app.mapping.items():
        entry['status'] = endpoint in allowed

    def snapshot(data):
        return {'status': 200, 'result': {'voice': app.controller.voice_events.status(),
                'route': app.controller.voice_route.status(), 'pcm': tap.records}}

    def translation(data):
        config.ENABLE_TRANSLATION = bool(data)
        return {'status': 200, 'result': config.ENABLE_TRANSLATION}

    app.mapping['/__test__/snapshot'] = {'status': True, 'variable': snapshot}
    app.mapping['/__test__/translation'] = {'status': True, 'variable': translation}
    for index in range(3):
        def busy(data, index=index):
            wait_release(f'worker-{index}')
            return {'status': 200, 'result': None}
        app.mapping[f'/__test__/busy/{index}'] = {'status': True, 'variable': busy}
    signal.signal(signal.SIGTERM, lambda *_: app._stop_event.set())
    app.startHandler()
    app.startReceiver()
    journal('ready', pid=os.getpid())
    try:
        while not app._stop_event.wait(.1):
            pass
    finally:
        (args.output / 'release').touch()
        route_closed = app.controller.voice_route.close()
        bus_closed = app.controller.voice_events.close()
        for thread in app._threads:
            if thread.name.startswith('main_handler'):
                thread.join(2)
        (args.output / 'backend-final.json').write_text(json.dumps({
            'route_closed': route_closed, 'bus_closed': bus_closed, 'pcm': tap.records,
            'voice': app.controller.voice_events.status(), 'route': app.controller.voice_route.status(),
        }, indent=2))
        module._cleanupCrashTraceIfEmpty()
        patches.undo()


if __name__ == '__main__':
    main()
