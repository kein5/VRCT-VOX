"""Monitor of converted voice: same blocks as the managed VC sink, never on its path."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import time
from types import SimpleNamespace

import pytest

from models.audio_routing.monitor_output import MonitorTee, monitor_spec, parse_monitor
from models.tts.speechcpp_tts import SpeechError
from models.voice_conversion.direct_voice import DirectVoice
from models.voice_conversion.router_protocol import BASE_STATE, encode, validate_health
from tools.voice_acceptance import wait_for

from test_controller_integration import controller_module  # noqa: F401
from test_direct_voice_controller import ConvertedBackend, app, managed, request  # noqa: F401
from test_seedvc_live import SINK, SOURCE, WORKER, send as send_block

linux = pytest.mark.skipif(sys.platform != 'linux', reason='Linux VC transport')
SEED = {'runtime': '/permitted/runtime', 'reference': '/permitted/reference.wav'}


class Sink:
    def __init__(self, *, gate=None, fail=False):
        self.data, self.closed, self.gate, self.fail = [], [], gate, fail

    def write(self, pcm, token):
        if self.gate is not None:
            while not self.gate.wait(.01):
                token.check()
        token.check()
        if self.fail:
            raise SpeechError('output_disconnected')
        self.data.append(pcm)

    def close(self, *, drain, token):
        self.closed.append(drain)


@contextmanager
def converted(tmp_path, monkeypatch, monitor, *, opener=None):
    """Seed-VC transport with real child pipes, fake capture/output and fake monitor device."""
    from models.voice_conversion import process as transport, seed_process
    runtime = tmp_path / 'runtime'
    for name in ('venv/bin', 'engine', 'assets'):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    (runtime / 'venv/bin/python').touch()
    (tmp_path / 'reference.wav').touch()
    captures, managed_sink, tees, children = [], Sink(), [], []

    class Capture:
        def __init__(self, endpoint, source, on_audio, on_error):
            self.on_audio = on_audio
            captures.append(self)

        def start(self):
            pass

        def request_stop(self):
            pass

        def stop(self):
            pass

    def launch(*args):
        child = subprocess.Popen([sys.executable, '-u', '-c', WORKER, 'converted', args[-1], 'seed-vc'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                                 env={**os.environ, 'PYTHONPATH': str(Path('src-python').resolve())})
        children.append(child)
        return child

    def tee(*args, **kwargs):
        tees.append((args, kwargs['exclude']))
        return MonitorTee(*args, output_factory=opener, **kwargs)
    monkeypatch.setattr(seed_process, '_launch', launch)
    monkeypatch.setattr(transport, 'PipeWireCapture', Capture)
    monkeypatch.setattr(transport, '_binding', lambda source: SINK)
    monkeypatch.setattr(transport, '_output', lambda endpoint: managed_sink)
    monkeypatch.setattr(transport, 'MonitorTee', tee)
    extra = {} if monitor is None else {'monitor': monitor}
    vc = seed_process.SeedProcess({'runtime': str(runtime), 'reference': str(tmp_path / 'reference.wav')}, **extra)
    try:
        vc.start(source=SOURCE)
        wait_for(lambda: captures and vc.health()['active'], timeout=3)
        yield vc, captures[0], managed_sink, tees
    finally:
        assert vc.close(timeout=3)
        assert all(child.poll() is not None for child in children)


def send(capture):
    # Capture stamps must increase across blocks: one 80 ms block per 100 ms.
    time.sleep(.1)
    send_block(capture)


def until_written(vc, main, count):
    try:
        wait_for(lambda: len(main.data) == count, timeout=3)
    except TimeoutError:
        raise AssertionError(vc.health()) from None


def opener_for(sink=None, error=None):
    calls = []

    def opener(device, rate, channels, *, exclude=()):
        calls.append((device, rate, channels, exclude))
        if error is not None:
            raise error
        return sink
    return opener, calls


@linux
def test_monitor_gets_the_same_converted_blocks_as_the_virtual_mic(tmp_path, monkeypatch):
    monitor_sink = Sink()
    opener, calls = opener_for(monitor_sink)
    with converted(tmp_path, monkeypatch, {'device': 'alsa_output.headphones', 'volume': 100}, opener=opener) as (
            vc, capture, main, tees):
        for count in range(1, 4):
            send(capture)
            until_written(vc, main, count)
        wait_for(lambda: len(monitor_sink.data) == 3, timeout=3)
        assert monitor_sink.data == main.data and main.data[0] == b'\2\0' * 3840
        assert calls == [('alsa_output.headphones', 48000, 1, (SINK.name,))]
        assert vc.health()['monitor_error'] is None and vc.health()['conversion_verified']
    assert monitor_sink.closed == [False]  # Stop never drains the monitor.


@linux
@pytest.mark.parametrize('fault', ['missing', 'unplugged', 'stalled'])
def test_monitor_failure_never_affects_converted_output(tmp_path, monkeypatch, fault):
    gate = Event()
    sink = Sink(gate=gate) if fault == 'stalled' else Sink(fail=fault == 'unplugged')
    opener, _ = opener_for(sink, SpeechError('output_missing') if fault == 'missing' else None)
    with converted(tmp_path, monkeypatch, {'device': '', 'volume': 50}, opener=opener) as (vc, capture, main, _):
        for count in range(1, 5):
            send(capture)
            until_written(vc, main, count)
        health = vc.health()
        assert main.data == [b'\2\0' * 3840] * 4
        assert health['active'] and health['error'] is None and health['conversion_verified']
        if fault != 'stalled':
            wait_for(lambda: vc.health()['monitor_error'] is not None)
            assert vc.health()['monitor_error'] == ('monitor_output_missing' if fault == 'missing'
                                                    else 'monitor_output_disconnected')
            assert vc.health()['active']
    gate.set()


@linux
def test_disabled_monitor_opens_nothing(tmp_path, monkeypatch):
    with converted(tmp_path, monkeypatch, None, opener=lambda *a, **k: pytest.fail('opened')) as (
            vc, capture, main, tees):
        send(capture)
        wait_for(lambda: main.data, timeout=3)
        assert tees == [] and vc.health()['monitor_error'] is None


def test_monitor_spec_crosses_processes_only_when_valid():
    assert monitor_spec(None) is None and parse_monitor(None) is None
    assert monitor_spec(('', 40)) == {'device': '', 'volume': 40}
    for bad in ({'device': 'vrct.managed.vc', 'volume': 50}, {'device': '', 'volume': 101},
                {'device': '', 'volume': True}, {'device': '', 'volume': 50, 'extra': 1},
                {'device': 'a\nb', 'volume': 50}, ['', 50]):
        with pytest.raises(ValueError, match='vc_monitor_invalid'):
            parse_monitor(bad)


def test_health_carries_only_fixed_monitor_codes():
    health = dict(BASE_STATE, kind='health', sent_ns=time.monotonic_ns(), monitor_error='monitor_output_missing')
    assert validate_health(health)['monitor_error'] == 'monitor_output_missing'
    for bad in ('alsa_output.usb device gone', 'vc_worker_eof', 7):
        with pytest.raises(ValueError):
            validate_health(dict(health, monitor_error=bad))
    legacy = {key: value for key, value in health.items() if key != 'monitor_error'}
    with pytest.raises(ValueError):
        validate_health(legacy)  # Router and owner ship together; the field is required.


class Backend(ConvertedBackend):
    def __init__(self):
        super().__init__()
        self.state['monitor_error'] = None


def test_direct_voice_forwards_monitor_to_converted_only():
    calls, backend = [], Backend()

    def factory(options, **kwargs):
        calls.append(kwargs)
        return backend
    owner = DirectVoice(passthrough_factory=lambda: pytest.fail('passthrough'), converted_factory=factory)
    owner.start(source=SOURCE, expected_generation=0, mode='converted', options=dict(SEED))
    assert calls == [{}]  # Disabled: the backend never receives a monitor.
    owner.stop()
    owner.start(source=SOURCE, expected_generation=owner.health()['generation'], mode='converted',
                options=dict(SEED), monitor={'device': '', 'volume': 70})
    assert calls[-1] == {'monitor': {'device': '', 'volume': 70}}
    backend.state['monitor_error'] = 'monitor_output_missing'
    health = owner.health()
    assert health['monitor_error'] == 'monitor_output_missing' and health['requested'] and health['error'] is None
    owner.close()


@linux
@pytest.mark.parametrize('monitor', [None, {'device': 'alsa_output.speakers', 'volume': 30}])
def test_router_worker_passes_the_monitor_to_the_worker(monkeypatch, monitor):
    from models.voice_conversion import router_worker as worker
    read, write = os.pipe()
    output_read, output_write = os.pipe()
    started, created = Event(), []

    class Process:
        def start(self, **kwargs):
            started.set()

        def health(self):
            return dict(BASE_STATE, requested=True, active=True, state='ready')

        def close(self, timeout):
            return True
    monkeypatch.setattr(worker, 'create_worker_process', lambda options, **kwargs: created.append(kwargs) or Process())
    incoming, outgoing = os.fdopen(read, 'rb', buffering=0), os.fdopen(output_write, 'wb', buffering=0)
    monkeypatch.setattr(worker, 'sys', SimpleNamespace(stdin=SimpleNamespace(buffer=incoming, fileno=incoming.fileno),
                                                     stdout=SimpleNamespace(buffer=outgoing, fileno=outgoing.fileno)))
    message = dict(kind='start', source=dict(cookie='1', serial='2', name='test.source', media_class='Audio/Source'),
                   options=dict(SEED))
    if monitor is not None:
        message['monitor'] = monitor
    os.write(write, encode(message))
    results = []
    thread = Thread(target=lambda: results.append(worker.main()), daemon=True)
    thread.start()
    try:
        assert started.wait(2)
        assert created == [{} if monitor is None else {'monitor': monitor}]
    finally:
        os.close(write)
        thread.join(2)
        incoming.close()
        outgoing.close()
        os.close(output_read)
    assert results == [0]


@linux
def test_router_worker_rejects_a_monitor_into_the_virtual_mic(monkeypatch):
    from models.voice_conversion import router_worker as worker
    read, write = os.pipe()
    output_read, output_write = os.pipe()
    monkeypatch.setattr(worker, 'create_worker_process', lambda *a, **k: pytest.fail('created'))
    incoming, outgoing = os.fdopen(read, 'rb', buffering=0), os.fdopen(output_write, 'wb', buffering=0)
    monkeypatch.setattr(worker, 'sys', SimpleNamespace(stdin=SimpleNamespace(buffer=incoming, fileno=incoming.fileno),
                                                     stdout=SimpleNamespace(buffer=outgoing, fileno=outgoing.fileno)))
    os.write(write, encode(dict(kind='start', options=dict(SEED), monitor={'device': 'vrct.managed.mix', 'volume': 50},
                                source=dict(cookie='1', serial='2', name='test.source', media_class='Audio/Source'))))
    try:
        assert worker.main() == 1
    finally:
        for stream in (incoming, outgoing):
            stream.close()
        os.close(write)
        os.close(output_read)


@linux
def test_isolated_owner_sends_the_monitor_in_its_start_request(monkeypatch, tmp_path):
    from models.voice_conversion import direct_voice, isolated
    monkeypatch.setattr(direct_voice, 'create_worker_process', lambda options: object())
    received = tmp_path / 'request.json'
    script = 'import sys; open(sys.argv[1], "wb").write(sys.stdin.buffer.readline())'

    def launch():
        return subprocess.Popen([sys.executable, '-c', script, str(received)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
    monkeypatch.setattr(isolated, '_launch', launch)
    for monitor in (None, {'device': '', 'volume': 80}):
        owner = (isolated.IsolatedVCProcess(dict(SEED)) if monitor is None
                 else isolated.IsolatedVCProcess(dict(SEED), monitor=monitor))
        owner.start(source=SOURCE)
        wait_for(lambda: not owner.health()['requested'], timeout=5)
        owner.close(timeout=3)
        sent = json.loads(received.read_bytes())
        assert sent.get('monitor') == monitor and ('monitor' in sent) is (monitor is not None)


def test_controller_uses_the_tts_monitor_setting_for_converted_start_only(app, monkeypatch):  # noqa: F811
    from models.voice_conversion import isolated
    c, raw, *_ = app
    calls, backends = [], []

    def factory(options, **kwargs):
        calls.append(kwargs)
        backends.append(Backend())
        return backends[-1]
    monkeypatch.setattr(isolated, 'IsolatedVCProcess', factory)
    managed(c)
    assert c.setVoiceSettings(dict(c.voice_events.settings.to_dict(), monitor='on', monitor_volume='60'))['status'] == 200
    assert c.startDirectVoice({**request(c), 'mode': 'converted', 'options': dict(SEED)})['status'] == 200
    assert calls == [{'monitor': {'device': '', 'volume': 60}}]
    backends[-1].state['monitor_error'] = 'monitor_output_missing'
    state = c.getDirectVoiceState()['result']
    assert state['monitor_error'] == 'monitor_output_missing' and state['active'] and state['error'] is None
    c.stopDirectVoice()
    assert c.setVoiceSettings(dict(c.voice_events.settings.to_dict(), monitor='off'))['status'] == 200
    assert c.startDirectVoice({**request(c), 'mode': 'converted', 'options': dict(SEED)})['status'] == 200
    assert calls[-1] == {}  # Disabled: no monitor reaches the VC process.
    c.stopDirectVoice()
