"""Explicit Linux source forwarding. Route health is not proof of voice conversion.

PCM stays inside pw-loopback. Its creating thread owns its lifetime; stopping
never touches the persistent virtual microphone or the independent TTS input.
"""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import select
import subprocess
import sys
from threading import Event, Lock, Thread, get_native_id
import time
from uuid import uuid4

from .pipewire_gate import VC_SINK

START_TIMEOUT = 3.0
MONITOR_INTERVAL = .1
BUILD = Path(__file__).resolve().parents[3] / 'build'


@dataclass(frozen=True)
class Endpoint:
    cookie: int
    serial: int
    name: str
    media_class: str


def _node(graph, name):
    matches = [n for n in graph if n.get('type') == 'PipeWire:Interface:Node'
               and n.get('info', {}).get('props', {}).get('node.name') == name]
    if len(matches) != 1:
        raise RuntimeError('source_bridge_endpoint_missing_or_ambiguous')
    return matches[0]


def _endpoint(graph, name, media_class):
    cores = [n['info']['cookie'] for n in graph if n.get('type') == 'PipeWire:Interface:Core']
    props = _node(graph, name)['info']['props']
    serial = props.get('object.serial')
    if (len(cores) != 1 or type(cores[0]) is not int or not 0 <= cores[0] <= 2**32 - 1
            or type(serial) is not int or not 0 <= serial <= 2**64 - 1
            or props.get('media.class') != media_class):
        raise RuntimeError('source_bridge_endpoint_invalid')
    return Endpoint(cores[0], serial, name, media_class)


def select_source(graph, name):
    source = _endpoint(graph, name, 'Audio/Source')
    props = _node(graph, name)['info']['props']
    if (name.startswith(('vrct.managed.', 'vrct.source-bridge.'))
            or 'vrct.managed.route' in props or 'vrct.source.bridge' in props):
        raise RuntimeError('source_bridge_feedback_source')
    return source


def _sink(graph):
    sink = _endpoint(graph, VC_SINK, 'Audio/Sink')
    if _node(graph, sink.name)['info']['props'].get('vrct.managed.route') != 'v1':
        raise RuntimeError('source_bridge_sink_invalid')
    return sink


def _read_graph():
    try:
        result = subprocess.run(['pw-dump'], capture_output=True, check=True, timeout=1)
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise RuntimeError('source_bridge_graph_unavailable') from exc


class _BridgeProcess:
    """Control the supervisor; authenticate streams against its reported child."""
    def __init__(self, supervisor, audio_pid):
        self.supervisor, self.pid = supervisor, audio_pid

    def poll(self):
        return self.supervisor.poll()

    def terminate(self):
        self.supervisor.terminate()

    def kill(self):
        self.supervisor.kill()

    def wait(self, timeout):
        return self.supervisor.wait(timeout=timeout)


def _audio_pid(process):
    if not select.select([process.stdout], [], [], 2)[0]:
        raise RuntimeError('source_bridge_launch_timeout')
    reply = os.read(process.stdout.fileno(), 64)
    if not reply.endswith(b'\n') or not reply[:-1].isdigit():
        raise RuntimeError('source_bridge_launch_failed')
    pid = int(reply[:-1])
    if pid <= 1 or pid == process.pid:
        raise RuntimeError('source_bridge_launch_failed')
    return pid


def _launch(source, sink, tag):
    common = ('vrct.source.bridge=v1 node.dont-fallback=true node.dont-reconnect=true '
              'node.dont-move=true node.linger=false state.restore-props=false')
    # Linux >=6.9 PIDFD_THREAD is O_EXCL in the public UAPI. Opening our own
    # nonleader control thread here prevents TID reuse and pre-main death races.
    try:
        owner_fd = os.pidfd_open(get_native_id(), os.O_EXCL)
    except (AttributeError, OSError) as exc:
        raise RuntimeError('source_bridge_thread_watch_unavailable') from exc
    try:
        supervisor = subprocess.Popen([
        str(BUILD / 'vrct-source-bridge'), str(os.getpid()),
        str(owner_fd),
        '--channels', '1', '--channel-map', 'MONO', '--latency', '10ms',
        '--capture-props', f'{common} node.name=vrct.source-bridge.{tag}.capture '
                           f'media.class=Stream/Input/Audio target.object={source.serial}',
        '--playback-props', f'{common} node.name=vrct.source-bridge.{tag}.playback '
                            f'media.class=Stream/Output/Audio target.object={sink.serial} '
                            'node.param.Props={mute=true}',
        ], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
           pass_fds=(owner_fd,))
    finally:
        os.close(owner_fd)
    try:
        return _BridgeProcess(supervisor, _audio_pid(supervisor))
    except BaseException:
        _reap(supervisor)
        raise
    finally:
        supervisor.stdout.close()


def _unmute(endpoint, tag):
    try:
        subprocess.run([str(BUILD / 'vrct-voice-gate'), str(endpoint.cookie),
                        str(endpoint.serial), '0', tag],
                       capture_output=True, check=True, timeout=2.5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('source_bridge_gate_failed') from exc


def _links(graph, source, sink, tag, pid, muted):
    """Reject extra input/output links, not just the absence of the desired pair."""
    if select_source(graph, source.name) != source or _sink(graph) != sink:
        raise RuntimeError('source_bridge_endpoint_changed')
    streams = []
    for suffix, media in [('capture', 'Stream/Input/Audio'), ('playback', 'Stream/Output/Audio')]:
        name = f'vrct.source-bridge.{tag}.{suffix}'
        endpoint = _endpoint(graph, name, media)
        item = _node(graph, name)
        props = item['info']['props']
        # Native streams identify their Client object; the server records its
        # authenticated PID there. application.process.id is client-controlled.
        clients = [n for n in graph if n.get('type') == 'PipeWire:Interface:Client'
                   and n.get('id') == props.get('client.id')]
        if (props.get('vrct.source.bridge') != 'v1' or len(clients) != 1
                or clients[0]['info']['props'].get('pipewire.sec.pid') != pid):
            raise RuntimeError('source_bridge_stream_owner_invalid')
        streams.append((item, endpoint))
    capture, playback = (item['id'] for item, _ in streams)
    expected = {(_node(graph, source.name)['id'], capture), (playback, _node(graph, sink.name)['id'])}
    observed = set()
    for item in graph:
        if item.get('type') != 'PipeWire:Interface:Link':
            continue
        info = item['info']
        pair = (info['output-node-id'], info['input-node-id'])
        if capture in pair or playback in pair:
            if pair not in expected or info.get('state') not in ('active', 'paused'):
                raise RuntimeError('source_bridge_links_invalid')
            observed.add(pair)
    if observed != expected:
        raise RuntimeError('source_bridge_links_missing')
    values = [p['mute'] for p in streams[1][0]['info'].get('params', {}).get('Props', []) if 'mute' in p]
    if len(values) != 1 or values[0] is not muted:
        raise RuntimeError('source_bridge_mute_unconfirmed')
    return streams[1][1]


def _signal(child):
    if child is not None and child.poll() is None:
        try:
            child.terminate()
        except ProcessLookupError:
            pass


def _reap(child):
    if child is None:
        return
    _signal(child)
    try:
        child.wait(timeout=.5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=.5)


@dataclass
class _Run:
    generation: int
    source: Endpoint
    tag: str = field(default_factory=lambda: uuid4().hex)
    stop: Event = field(default_factory=Event)
    child: object = None
    thread: object = None


class SourceBridge:
    def __init__(self):
        self._lock = Lock()
        self._source = None
        self._run = None
        self._state = dict(requested=False, active=False, pending=False, error=None,
                           generation=0, conversion_verified=False)

    def health(self):
        with self._lock:
            return dict(self._state)

    def _stop_locked(self):
        self._state.update(requested=False, active=False, pending=False,
                           generation=self._state['generation'] + 1)
        if self._run:
            self._run.stop.set()
            return self._run.child
        return None

    def configure(self, source):
        if not isinstance(source, Endpoint) or source.media_class != 'Audio/Source':
            raise ValueError('source_bridge_source_required')
        with self._lock:
            child = self._stop_locked()
            self._source = source
            self._state['error'] = None
        _signal(child)

    def start(self):
        if not sys.platform.startswith('linux'):
            raise RuntimeError('source_bridge_linux_only')
        with self._lock:
            if self._state['requested']:
                return
            if self._run and self._run.thread.is_alive():
                raise RuntimeError('source_bridge_stopping')
            if self._source is None:
                raise RuntimeError('source_bridge_source_required')
            self._state.update(requested=True, active=False, pending=True, error=None,
                               generation=self._state['generation'] + 1)
            run = self._run = _Run(self._state['generation'], self._source)
            run.thread = Thread(target=self._work, args=(run,), daemon=True, name='VRCT source bridge')
            run.thread.start()

    def stop(self):
        with self._lock:
            child = self._stop_locked()
        _signal(child)

    def close(self, timeout=3):
        self.stop()
        with self._lock:
            run = self._run
        if run:
            run.thread.join(timeout)
        return not run or not run.thread.is_alive()

    def _update(self, run, **values):
        with self._lock:
            if self._state['generation'] == run.generation and not run.stop.is_set():
                self._state.update(values)

    def _work(self, run):
        try:
            graph = _read_graph()
            if select_source(graph, run.source.name) != run.source:
                raise RuntimeError('source_bridge_source_changed')
            sink = _sink(graph)
            if run.stop.is_set():
                return
            child = _launch(run.source, sink, run.tag)
            with self._lock:
                run.child = child
            deadline = time.monotonic() + START_TIMEOUT
            while not run.stop.is_set():
                if child.poll() is not None:
                    raise RuntimeError('source_bridge_process_exited')
                graph = _read_graph()
                # Replaced endpoints never become acceptable by waiting longer.
                if select_source(graph, run.source.name) != run.source or _sink(graph) != sink:
                    raise RuntimeError('source_bridge_endpoint_changed')
                try:
                    output = _links(graph, run.source, sink, run.tag, child.pid, True)
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise
                    run.stop.wait(MONITOR_INTERVAL)
            else:
                return
            if run.stop.is_set():
                return
            _unmute(output, run.tag)
            while not run.stop.is_set():
                if child.poll() is not None:
                    raise RuntimeError('source_bridge_process_exited')
                _links(_read_graph(), run.source, sink, run.tag, child.pid, False)
                self._update(run, active=True, pending=False)
                run.stop.wait(MONITOR_INTERVAL)
        except Exception as exc:
            # No arbitrary subprocess output/paths in UI-facing diagnostics.
            code = str(exc) if isinstance(exc, RuntimeError) and str(exc).startswith('source_bridge_') else 'source_bridge_control_failed'
            self._update(run, requested=False, active=False, pending=False, error=code)
        finally:
            try:
                _reap(run.child)
            finally:
                self._update(run, requested=False, active=False, pending=False)
