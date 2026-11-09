"""Windows routes for speech.cpp, realtime ASR and direct voice, without models or devices."""
import copy
import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
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


@pytest.mark.parametrize('spec', ['backend.spec', 'backend_cuda.spec'])
def test_both_windows_builds_name_the_sidecar_for_the_microphone_question(spec):
    assert 'version=sidecar_version(ROOT)' in (ROOT / 'spec' / spec).read_text(encoding='utf-8')


def test_the_sidecar_version_carries_the_app_name(tmp_path):
    resources = importlib.import_module('tools.windows_voice_resources')
    (tmp_path / 'package.json').write_text('{"version": "1.2.3-beta.4"}', encoding='utf-8')
    path = resources.sidecar_version(tmp_path)
    text = Path(path).read_text(encoding='utf-8')
    assert 'filevers=(1, 2, 3, 4)' in text
    assert "StringStruct('FileDescription', 'VRCT-VOX')" in text
    assert "StringStruct('FileVersion', '1.2.3-beta.4')" in text


def test_pyinstaller_reads_the_sidecar_version_file(tmp_path):
    versioninfo = pytest.importorskip('PyInstaller.utils.win32.versioninfo')
    resources = importlib.import_module('tools.windows_voice_resources')
    (tmp_path / 'package.json').write_text('{"version": "1.2.3"}', encoding='utf-8')
    info = versioninfo.load_version_info_from_text_file(resources.sidecar_version(tmp_path))
    assert info.ffi.fileVersionMS == (1 << 16) | 2 and info.ffi.fileVersionLS == 3 << 16
    assert 'VRCT-VOX' in str(info)


def test_a_rejected_seed_setting_gives_its_graphs_back(monkeypatch):
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)))
    try:
        graphs = importlib.import_module('integrations.seed_vc.graphs')
        replay = graphs.Replay(None)
        engine = SimpleNamespace(config=SimpleNamespace(max_prompt_length=0, diffusion_steps=0))
        now = [0.]
        monkeypatch.setattr(graphs, 'time', SimpleNamespace(perf_counter=lambda: now[0]))

        class Session:
            def convert(self, _):
                replay.entries[engine.config.max_prompt_length] = True
                now[0] += .1 if engine.config.max_prompt_length == 3.0 else .01
                return b''

        assert graphs.fit_block(engine, Session(), None) == (2.0, 10)
        assert list(replay.entries) == [2.0]
    finally:
        sys.modules.pop('integrations.seed_vc.graphs', None)


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
    assert ('live_worker.py', 'voice_worker/integrations/rvc') in pairs
    assert ('LICENSE.upstream', 'voice_worker/integrations/rvc') in pairs
    assert ('requirements.lock', 'voice_worker/integrations/rvc') not in pairs
    assert ('owned_child.py', 'voice_worker/src-python/models') in pairs
    assert ('protocol.py', 'voice_worker/src-python/models/voice_conversion') in pairs


def test_windows_resources_carry_what_the_runtime_setup_and_seed_worker_read():
    m = importlib.import_module('tools.windows_voice_resources')
    pairs = {(Path(source).name, target) for source, target in m.voice_datas(ROOT)}
    assert ('requirements-cuda-windows.lock', 'voice_worker/integrations/rvc') in pairs
    assert ('requirements-windows.lock', 'voice_worker/integrations/rvc') in pairs
    assert ('requirements-windows.lock', 'voice_worker/integrations/seed_vc') in pairs
    assert ('offline-loader.patch', 'voice_worker/integrations/seed_vc') in pairs
    assert ('graphs.py', 'voice_worker/integrations/seed_vc') in pairs
    assert ('seedvc_artifacts.py', 'voice_worker/tools') in pairs
    assert ('seed-vc-poc-artifacts.json', 'voice_worker/docs/voice-stack') in pairs
    assert ('requirements.lock', 'voice_worker/integrations/seed_vc') not in pairs


def test_the_build_check_names_what_a_windows_tree_lacks(tmp_path):
    m = importlib.import_module('tools.windows_voice_resources')
    assert 'build/speechcpp/speech.exe' in m.missing_files(tmp_path)
    assert 'licenses/python' in m.missing_files(tmp_path)
    for name in m.REQUIRED:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text('x')
    (tmp_path / 'licenses/python/soxr-1.1.0').mkdir(parents=True)
    (tmp_path / 'licenses/python/soxr-1.1.0/COPYING').write_text('x')
    assert m.missing_files(tmp_path) == []


def test_the_build_collects_the_license_texts_notice_md_promises():
    m = importlib.import_module('tools.windows_voice_resources')
    rows = m.notice_toc()
    assert all(target.startswith('licenses/python/') and kind == 'DATA' for target, _, kind in rows)
    assert all(Path(source).is_file() for _, source, _ in rows)


def test_a_frozen_worker_does_not_start_inside_the_sidecars_python(tmp_path, monkeypatch):
    """-m puts the working directory first, and _internal holds 3.11 extension modules."""
    monkeypatch.setattr(rvc_process, 'ROOT', tmp_path)
    assert rvc_process.worker_root() == tmp_path
    (tmp_path / 'voice_worker').mkdir()
    assert rvc_process.worker_root() == tmp_path / 'voice_worker'


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


def test_translated_speech_can_silence_the_voice_on_a_device_route():
    backends = []

    class Backend:
        def __init__(self, **kwargs):
            self.muted = []
            backends.append(self)

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

    voice = dv.DirectVoice(passthrough_factory=lambda **kwargs: Backend(**kwargs))
    voice.set_monitor_muted(False)
    voice.set_suppressed(True)
    voice.start(source=SOURCE, expected_generation=0, output=DEVICE)
    assert backends[0].muted == [True]
    voice.set_suppressed(False)
    assert backends[0].muted == [True, False]
    voice.set_monitor_muted(True)
    voice.set_suppressed(True)
    voice.set_monitor_muted(False)  # Resuming does not lift the suppression.
    assert backends[0].muted[-1] is True
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


def test_a_stop_records_how_late_the_blocks_were(monkeypatch):
    logged = []
    monkeypatch.setattr(vp, 'printLog', lambda log, data=None: logged.append((log, data)))
    process = vp.VCProcess(engine='rvc', output=DEVICE)
    stale = time.monotonic_ns() - vp.LATE_NS - 100_000_000
    for _ in range(vp.LATE_WINDOW // 2):
        process._next_block(block(process, stale))
    process._rounds.extend([20_000_000, 30_000_000, 400_000_000])
    process._fail('vc_capture_overrun')
    [(name, data)] = logged
    assert name == 'voice conversion stopped'
    assert data['error'] == 'vc_capture_overrun'
    assert data['late_blocks'] == vp.LATE_WINDOW // 2 and data['window'] == vp.LATE_WINDOW // 2
    assert data['block_age_ms']['max'] >= 340
    assert data['round_trip_ms'] == dict(median=30.0, max=400.0)


def test_only_the_first_failure_is_recorded(monkeypatch):
    logged = []
    monkeypatch.setattr(vp, 'printLog', lambda log, data=None: logged.append(data))
    process = vp.VCProcess(engine='rvc', output=DEVICE)
    process._fail('vc_worker_eof')
    process._fail('vc_capture_overrun')
    assert [row['error'] for row in logged] == ['vc_worker_eof']
    assert logged[0]['block_age_ms'] is None and logged[0]['round_trip_ms'] is None


def test_a_stop_the_user_asked_for_records_nothing(monkeypatch):
    logged = []
    monkeypatch.setattr(vp, 'printLog', lambda log, data=None: logged.append(data))
    process = vp.VCProcess(engine='rvc', output=DEVICE)
    process.stop()
    process._fail('cancelled')
    assert logged == []


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


def test_windows_start_needs_an_output_for_every_engine(stub):
    module, controller, settings = stub
    start = module.Controller._directOutput
    with pytest.raises(RuntimeError, match='source_bridge_output_required'):
        start(controller, 'converted', {'engine': 'rvc'})
    settings.output_device = DEVICE
    assert start(controller, 'converted', {'engine': 'rvc'}) == DEVICE
    assert start(controller, 'passthrough', {}) == DEVICE
    assert start(controller, 'converted', {'runtime': 'r', 'reference': 'x'}) == DEVICE


def test_seed_worker_arguments_match_its_parser(monkeypatch):
    from models.voice_conversion import seed_process
    calls = []
    monkeypatch.setattr(seed_process, 'launch_owned', lambda args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(seed_process.sys, 'platform', 'win32')
    seed_process._launch(Path('R'), Path('voice.wav'), 'a' * 32)
    args, kwargs = calls[0]
    assert args[1:4] == ['-u', '-m', 'integrations.seed_vc.live_worker']
    assert args[args.index('--reference') + 1] == 'voice.wav' and args[args.index('--session') + 1] == 'a' * 32
    assert kwargs['realtime'] is True and kwargs['stderr'] == subprocess.DEVNULL


def test_seed_process_takes_the_output_device(tmp_path):
    from models.voice_conversion import seed_process
    python = rvc_process.runtime_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.write_text('')
    (tmp_path / 'engine').mkdir()
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'voice.wav').write_text('')
    process = seed_process.SeedProcess(dict(runtime=str(tmp_path), reference=str(tmp_path / 'voice.wav')), output=DEVICE)
    assert process._route.device == DEVICE


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


@pytest.mark.parametrize('platform,allowed', [('win32', True), ('linux', False)])
def test_silencing_the_voice_for_translated_speech_needs_no_managed_route_on_windows(monkeypatch, platform, allowed):
    from models.tts import settings as tts
    monkeypatch.setattr(tts.sys, 'platform', platform)
    values = dict(routing='external', output_device=DEVICE, mic_mode='translated', direct_policy='suppress')
    if allowed:
        assert tts.VoiceSettings.from_dict(values).direct_policy == 'suppress'
    else:
        with pytest.raises(ValueError, match='managed routing'):
            tts.VoiceSettings.from_dict(values)


def sources():
    return [{'id': dict(cookie=1, serial=0, name='["Windows WASAPI", "Surface Stereo Microphones (Surface High Definition Audio)"]',
                        media_class='Audio/Source'),
             'label': 'Surface Stereo Microphones (Surface High Definition Audio)'},
            {'id': dict(cookie=2, serial=0, name='["Windows WASAPI", "Mic (USB)"]', media_class='Audio/Source'),
             'label': 'Mic (USB)'}]


@pytest.mark.parametrize('host,selected,index', [
    ('MME', 'Surface Stereo Microphones (Sur', 0), ('Windows WASAPI', 'Mic (USB)', 1), ('MME', 'Mic (USB)', 1),
    ('Windows DirectSound', 'Surface Stereo Microphones (Surface High Definition Audio)', 0)])
def test_the_device_page_mic_is_the_voice_input_whichever_host_it_came_from(
        controller_module, monkeypatch, host, selected, index):  # noqa: F811
    monkeypatch.setattr(controller_module, 'config', SimpleNamespace(SELECTED_MIC_HOST=host, SELECTED_MIC_DEVICE=selected))
    controller = SimpleNamespace(_directUsesOutputDevice=lambda: True)
    rows = sources()
    assert controller_module.Controller._preferredDirectSource(controller, rows) == rows[index]['id']


def test_an_unknown_device_page_mic_falls_back_to_the_system_default(controller_module, monkeypatch):  # noqa: F811
    monkeypatch.setattr(controller_module, 'config', SimpleNamespace(SELECTED_MIC_HOST='MME', SELECTED_MIC_DEVICE='NoDevice'))
    rows = sources()
    monkeypatch.setattr(controller_module, 'default_endpoint',
                        lambda source: SimpleNamespace(name=rows[1]['id']['name']))
    controller = SimpleNamespace(_directUsesOutputDevice=lambda: True)
    assert controller_module.Controller._preferredDirectSource(controller, rows) == rows[1]['id']

    def feedback(source):
        raise ValueError('realtime_default_endpoint_feedback')

    monkeypatch.setattr(controller_module, 'default_endpoint', feedback)
    assert controller_module.Controller._preferredDirectSource(controller, rows) is None


def test_saved_outputs_reach_the_device_list(controller_module, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(controller_module, 'enumerate_outputs', lambda keep=(): seen.append(keep) or [])
    settings = SimpleNamespace(output_device='["MME", "CABLE Input (VB-Audio Virtual C"]', monitor_device='')
    controller = SimpleNamespace(voice_events=SimpleNamespace(settings=settings))
    assert controller_module.Controller.getVoiceOutputDevices(controller)['status'] == 200
    assert seen == [(settings.output_device, '')]


def test_captions_refuse_the_voice_cable_before_starting_a_server(controller_module, monkeypatch):  # noqa: F811
    """Starting one first left it stopping, which then refused the next, valid start."""
    from threading import Lock
    endpoint = Endpoint(1, 0, '["Windows WASAPI", "CABLE Output (VB-Audio Virtual Cable)"]', 'Audio/Source')
    monkeypatch.setattr(controller_module, 'realtime_endpoint', lambda settings, source: endpoint)
    monkeypatch.setattr(controller_module, 'normalize_realtime_settings', lambda value: dict(mic={}, server='bundled'))
    started = []
    controller = SimpleNamespace(
        _realtime_lock=Lock(), _realtime_closed=False, _realtime_generation=dict(mic=0), _realtime_settings={},
        voice_events=SimpleNamespace(settings=SimpleNamespace(output_device=DEVICE)), _directUsesOutputDevice=lambda: True,
        _awaitAsrServer=lambda *args: started.append(args))
    controller._carriesOwnVoice = lambda row: controller_module.Controller._carriesOwnVoice(controller, row)
    code, options = controller_module.Controller._prepareRealtimeToggle(controller, 'mic', 0)
    assert (code, options, started) == ('realtime_endpoint_feedback', None, [])


def test_leaving_the_bundled_server_clears_a_toggle_shown_on(controller_module, monkeypatch):  # noqa: F811
    from threading import Lock, RLock
    monkeypatch.setattr(controller_module.sys, 'platform', 'win32')
    sent = []
    controller = SimpleNamespace(
        _realtime_settings=dict(server='external'), _realtime_toggle_shown=dict(mic=True, speaker=False),
        _realtime_toggle_lock=RLock(), _realtime_lock=Lock(), _realtimeActiveLocked=lambda source: False,
        _releaseAsrServer=lambda: sent.append('released'),
        run=lambda status, endpoint, result: sent.append((status, endpoint, result)))
    controller._realtimeToggles = lambda: controller_module.Controller._realtimeToggles(controller)
    controller_module.Controller._publishRealtimeToggle(controller, 'mic')
    assert sent == [(200, '/set/disable/transcription_send', False), 'released']
    sent.clear()
    controller_module.Controller._publishRealtimeToggle(controller, 'speaker')
    assert sent == []
