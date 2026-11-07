"""Windows routes for speech.cpp, realtime ASR and direct voice, without models or devices."""
import copy
import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace
import zipfile

import pytest

from models.audio_routing.source_bridge import Endpoint
from models.speech_server import runtime as rt
from models.voice_conversion import direct_voice as dv
from models.voice_conversion import isolated
from models.voice_conversion import process as vp
from models.voice_conversion import rvc_process

from test_controller_integration import controller_module  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
OPTIONS = dict(model=r'C:\m\tts.gguf', vad_model='', voice_file='', device='auto', low_latency=False)
DEVICE = '["Windows WASAPI", "CABLE Input (VB-Audio Virtual Cable)"]'
SOURCE = Endpoint(1, 0, '["Windows WASAPI", "Microphone (USB)"]', 'Audio/Source')
windows = pytest.mark.skipif(sys.platform != 'win32', reason='Windows process behaviour')


def test_speech_command_line_matches_the_linux_helper(monkeypatch):
    calls = []
    monkeypatch.setattr(rt, 'launch_owned', lambda args, **kwargs: calls.append((args, kwargs)))
    server = rt.SpeechServer('asr', dict(OPTIONS, vad_model=r'C:\m\vad.gguf', device='gpu'))
    server._launch_windows(Path(r'C:\app\speech.exe'))
    server = rt.SpeechServer('japanese', dict(OPTIONS, voice_file=r'C:\m\voice.gguf'))
    server._launch_windows(Path(r'C:\app\speech.exe'))
    assert calls[0][0][1:] == ['serve', r'C:\m\tts.gguf', r'C:\m\vad.gguf', '--host', '127.0.0.1',
                               '--port', '0', '--device', 'gpu']
    assert calls[1][0][-2:] == ['--add-voice', r'custom=C:\m\voice.gguf']
    assert calls[0][1]['env']['NO_COLOR'] == '1'


FAKE_SERVER = '''
import json, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {'/health': {'status': 'ok'},
                '/v1/models': {'data': [{'speech': {'task': 'synthesis', 'device': 'Vulkan0'}}]}}[self.path]
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass

server = HTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
sys.stderr.buffer.write(b'API at http://127.0.0.1:%d/v1\\r\\n' % server.server_port)
sys.stderr.buffer.flush()
import time
time.sleep(60)
'''


@windows
def test_a_ready_line_ending_in_crlf_is_recognised_and_stop_ends_the_child(tmp_path, monkeypatch):
    script = tmp_path / 'server.py'
    script.write_text(FAKE_SERVER, encoding='utf-8')
    real = rt.launch_owned
    monkeypatch.setattr(rt, 'launch_owned', lambda args, **kwargs: real(
        [sys.executable, str(script)], **kwargs))
    monkeypatch.setattr(rt.listener_monitors, 'own', lambda *args: None)
    monkeypatch.setattr(rt.listener_monitors, 'forget', lambda *args: None)
    server = rt.SpeechServer('japanese', OPTIONS, binary=sys.executable)
    server.start()
    deadline = time.monotonic() + 30
    while server.health()['state'] == 'preparing' and time.monotonic() < deadline:
        time.sleep(.02)
    assert server.health()['state'] == 'ready', server.health()
    child = server._child
    assert server.close(timeout=5)
    assert server.health() == dict(state='stopped', base_url=None, error_code=None)
    assert child.poll() is not None


@windows
def test_a_missing_vulkan_library_is_named(tmp_path, monkeypatch):
    real = rt.launch_owned
    monkeypatch.setattr(rt, 'launch_owned', lambda args, **kwargs: real(
        [sys.executable, '-c', f'import ctypes; ctypes.windll.kernel32.ExitProcess(ctypes.c_uint({rt.DLL_NOT_FOUND}))'],
        **kwargs))
    server = rt.SpeechServer('japanese', OPTIONS, binary=sys.executable)
    server.start()
    deadline = time.monotonic() + 30
    while server.health()['state'] == 'preparing' and time.monotonic() < deadline:
        time.sleep(.02)
    assert server.health()['error_code'] == 'speech_server_vulkan_missing'
    assert server.close(timeout=3)


def test_windows_bundle_keeps_only_the_executable_and_the_notices(tmp_path):
    m = importlib.import_module('tools.speechcpp_bundle')
    archive = tmp_path / 'speech.zip'
    with zipfile.ZipFile(archive, 'w') as out:
        for name, value in (('speech.exe', b'fake'), ('speech.dll', b'library'),
                            ('speech.h', b'header'), ('speech.lib', b'import')):
            out.writestr(name, value)
    asset = copy.deepcopy(m.load_manifest()['assets']['windows-x64-vulkan'])
    data = archive.read_bytes()
    asset.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    output = tmp_path / 'bundle'
    result = m.stage_bundle(archive, output, asset)
    files = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
    assert 'speech.exe' in files and not {'speech', 'speech.dll', 'speech.h', 'speech.lib'} & files
    assert result['variant'] == 'windows-x64-vulkan'
    assert m.verify_bundle(output) == result


def test_windows_resources_carry_the_engine_and_the_worker_contract(tmp_path):
    m = importlib.import_module('tools.windows_voice_resources')
    bundle = tmp_path / 'build/speechcpp'
    (bundle / 'notices').mkdir(parents=True)
    (bundle / 'speech.exe').write_bytes(b'x')
    (bundle / 'bundle.json').write_text('{}')
    (bundle / 'notices/NOTICE.md').write_text('n')
    (tmp_path / 'integrations/rvc').mkdir(parents=True)
    for name in ('live_worker.py', 'LICENSE.upstream', 'requirements.lock'):
        (tmp_path / 'integrations/rvc' / name).write_text('x')
    pairs = {(Path(source).name, target) for source, target in m.voice_datas(tmp_path)}
    assert ('speech.exe', 'build/speechcpp') in pairs
    assert ('NOTICE.md', 'build/speechcpp/notices') in pairs
    assert ('live_worker.py', 'integrations/rvc') in pairs
    assert ('LICENSE.upstream', 'integrations/rvc') in pairs
    assert ('requirements.lock', 'integrations/rvc') not in pairs
    assert ('owned_child.py', 'src-python/models') in pairs
    assert ('protocol.py', 'src-python/models/voice_conversion') in pairs


def test_every_module_the_worker_imports_ships_with_it():
    """External interpreters cannot read the frozen PYZ, so a new import must be listed."""
    resources = importlib.import_module('tools.windows_voice_resources')
    for source in ('owned_child.py', 'voice_conversion/protocol.py', 'voice_conversion/settings.py'):
        text = (ROOT / 'src-python/models' / source).read_text(encoding='utf-8')
        imports = [line.split()[1] for line in text.splitlines() if line.startswith('from models.')]
        for name in imports:
            assert name.removeprefix('models.').replace('.', '/') + '.py' in resources.CONTRACT


def test_rvc_runtime_python_follows_the_platform(monkeypatch):
    runtime = Path('runtime')
    monkeypatch.setattr(rvc_process.sys, 'platform', 'win32')
    assert rvc_process.runtime_python(runtime) == runtime / 'venv/Scripts/python.exe'
    monkeypatch.setattr(rvc_process.sys, 'platform', 'linux')
    assert rvc_process.runtime_python(runtime) == runtime / 'venv/bin/python'


def test_rvc_worker_arguments_match_the_linux_helper(monkeypatch):
    calls = []
    monkeypatch.setattr(rvc_process, 'launch_owned', lambda args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(rvc_process.sys, 'platform', 'win32')
    rvc_process._launch(Path('R'), dict(model='m.pth', index='m.index', pitch=-2, index_rate=.5), 'a' * 32)
    args, kwargs = calls[0]
    assert args[1:5] == ['-u', '-m', 'integrations.rvc.live_worker', '--engine']
    assert args[args.index('--pitch') + 1] == '-2' and args[args.index('--index-rate') + 1] == '0.5'
    assert kwargs['realtime'] is True and kwargs['stderr'] == subprocess.DEVNULL


def test_source_check_compares_git_paths_on_every_platform(tmp_path, monkeypatch):
    loader = importlib.import_module('integrations.rvc.loader')
    (tmp_path / 'infer').mkdir()
    (tmp_path / 'infer/module.py').write_text('')

    def git(command, **kwargs):
        return {'rev-parse': loader.COMMIT.encode(), 'diff': b'', 'ls-files': b'infer/module.py\n'}[command[3]]

    monkeypatch.setattr(loader.subprocess, 'check_output', git)
    loader.require_source(tmp_path)


def test_direct_voice_hands_the_device_to_both_producers_and_forwards_mute():
    calls = []

    class Backend:
        def __init__(self, label, **kwargs):
            calls.append((label, kwargs))
            self.muted = []

        def set_monitor_muted(self, muted):
            self.muted.append(muted)

        def start(self, *, source):
            pass

        def stop(self):
            pass

        def close(self, timeout=3):
            return True

        def health(self):
            return dict(requested=True, active=True)

    voice = dv.DirectVoice(passthrough_factory=lambda **kwargs: Backend('original', **kwargs),
                           converted_factory=lambda options, **kwargs: Backend('converted', **kwargs))
    voice.set_monitor_muted(False)
    voice.start(source=SOURCE, expected_generation=0, output=DEVICE)
    assert calls[-1] == ('original', {'output': DEVICE})
    backend = voice._backend
    assert backend.muted == [False]
    voice.set_monitor_muted(True)
    assert backend.muted == [False, True]
    voice.stop()
    options = dict(engine='rvc', runtime='r', model='m.pth', index='', pitch=0, index_rate=0)
    voice.start(source=SOURCE, expected_generation=voice.health()['generation'], mode='converted',
                options=options, output=DEVICE)
    assert calls[-1] == ('converted', {'output': DEVICE})
    voice.close()


def test_a_managed_route_keeps_its_gate_and_a_device_route_silences_the_voice():
    managed = vp.VCProcess(engine='rvc')
    managed._monitor_muted = True
    assert managed._audible(b'\1\2') == b'\1\2'
    device = vp.VCProcess(engine='rvc', output=DEVICE)
    device._monitor_muted = True
    assert device._audible(b'\1\2') == b'\0\0'
    device._monitor_muted = False
    assert device._audible(b'\1\2') == b'\1\2'


def block(process, end_ns, sequence=0):
    from models.voice_conversion import protocol as p
    return dict(p.input_info(process._session, sequence, end_ns - p.BLOCK_NS), pcm_bytes=p.PCM_BYTES)


def test_device_route_drops_a_late_block_and_keeps_worker_sequence_contiguous():
    process = vp.VCProcess(engine='rvc', output=DEVICE)
    now = time.monotonic_ns()
    first = process._next_block(block(process, now, 7))
    late = process._next_block(block(process, now - vp.LATE_NS - 100_000_000, 8))
    second = process._next_block(block(process, now, 9))
    assert first['sequence'] == 0 and late is None and second['sequence'] == 1


def test_device_route_stops_only_when_most_recent_blocks_are_late():
    process = vp.VCProcess(engine='rvc', output=DEVICE)
    stale = time.monotonic_ns() - vp.LATE_NS - 100_000_000
    for _ in range(vp.LATE_WINDOW // 2):
        assert process._next_block(block(process, stale)) is None
    with pytest.raises(vp.p.ProtocolError, match='vc_capture_overrun'):
        process._next_block(block(process, stale))


def test_device_route_recovers_after_a_stall():
    process = vp.VCProcess(engine='rvc', output=DEVICE)
    stale = time.monotonic_ns() - vp.LATE_NS - 100_000_000
    for _ in range(30):
        process._next_block(block(process, stale))
    for _ in range(vp.LATE_WINDOW):
        assert process._next_block(block(process, time.monotonic_ns())) is not None
    assert sum(process._late) == 0


def test_a_full_input_queue_keeps_the_newest_block_on_the_device_route():
    process = vp.VCProcess(engine='rvc', output=DEVICE)
    for value in range(process._queue.maxsize):
        process._queue.put_nowait(({'n': value}, b''))
    process._partial.extend(b'x' * 4)
    assert process._replace_oldest({'n': 99}) is False
    items = [process._queue.get_nowait()[0]['n'] for _ in range(process._queue.maxsize)]
    assert items == [1, 2, 3, 99]


def test_device_route_checks_devices_at_start_but_not_for_every_block(monkeypatch):
    route = importlib.import_module('models.audio_routing.windows_route')
    calls = []
    monkeypatch.setattr(route, '_check_devices', lambda source, device: calls.append(device))
    target = route.WindowsRoute(DEVICE)
    assert target.bind(SOURCE) == target.bind(SOURCE, wait=False)
    assert calls == [DEVICE]


def test_router_request_carries_the_device_and_starts_with_mute_control(monkeypatch):
    sent = []
    monkeypatch.setattr(dv, 'create_worker_process', lambda options, **kwargs: None)
    process = isolated.IsolatedVCProcess(
        dict(engine='rvc', runtime='r', model='m.pth', index='', pitch=0, index_rate=0), output=DEVICE)
    assert process._controlled and not process._router_seen
    process.set_monitor_muted(False)
    monkeypatch.setattr(process, '_run', lambda request, source: sent.append(request))
    monkeypatch.setattr(isolated, '_validate', lambda source, kind: None)
    monkeypatch.setattr(isolated, 'Thread', lambda target, args, **kwargs: SimpleNamespace(
        start=lambda: target(*args), is_alive=lambda: False))
    process.start(source=SOURCE)
    frame = sent[0]
    assert b'"output"' in frame and b'"monitor_control"' in frame and b'"muted":false' in frame


@pytest.fixture
def stub(controller_module):  # noqa: F811
    settings = SimpleNamespace(routing='external', output_device='', monitor_choice=None)
    return controller_module, SimpleNamespace(voice_events=SimpleNamespace(settings=settings),
                                              _directUsesOutputDevice=lambda: True), settings


def test_windows_start_needs_an_output_and_refuses_seed_vc(stub):
    module, controller, settings = stub
    start = module.Controller._directOutput
    with pytest.raises(RuntimeError, match='source_bridge_output_required'):
        start(controller, 'converted', {'engine': 'rvc'})
    settings.output_device = DEVICE
    assert start(controller, 'converted', {'engine': 'rvc'}) == DEVICE
    assert start(controller, 'passthrough', {}) == DEVICE
    with pytest.raises(RuntimeError, match='vc_engine_linux_only'):
        start(controller, 'converted', {'runtime': 'r', 'reference': 'x'})


def test_linux_start_still_needs_the_managed_route(stub, monkeypatch):
    module, controller, settings = stub
    controller._directUsesOutputDevice = lambda: False
    monkeypatch.setattr(module.sys, 'platform', 'linux')
    with pytest.raises(RuntimeError, match='source_bridge_managed_required'):
        module.Controller._directOutput(controller, 'converted', {'engine': 'rvc'})
    settings.routing = 'managed'
    assert module.Controller._directOutput(controller, 'converted', {'engine': 'rvc'}) is None


@pytest.mark.parametrize('platform,server,expected', [
    ('linux', 'external', True), ('linux', 'bundled', True),
    ('win32', 'external', False), ('win32', 'bundled', True), ('darwin', 'bundled', False)])
def test_main_toggles_follow_the_server_choice_on_windows(controller_module, monkeypatch, platform, server, expected):  # noqa: F811
    monkeypatch.setattr(controller_module.sys, 'platform', platform)
    controller = SimpleNamespace(_realtime_settings=dict(server=server))
    assert controller_module.Controller._realtimeToggles(controller) is expected
