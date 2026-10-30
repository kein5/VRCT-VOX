"""Read-only, fail-closed route evidence for a prepared local VRChat test.

Consume pw-dump --monitor changes, rather than inferring interval safety from
two snapshots. This detects reported changes; it does not prevent fallback or
prove what VRChat does with the PCM. No daemon, node or link is modified.
"""
import codecs
from copy import deepcopy
import json
import signal
import subprocess
from threading import Event, Lock, Thread
import time


class JSONArrays:
    def __init__(self):
        self.buffer = ''

    def feed(self, text):
        self.buffer += text
        result = []
        while self.buffer.strip():
            self.buffer = self.buffer.lstrip()
            try:
                value, end = json.JSONDecoder().raw_decode(self.buffer)
            except json.JSONDecodeError:
                if len(self.buffer) > 16_000_000:
                    raise ValueError('monitor_document_too_large')
                break
            if not isinstance(value, list):
                raise ValueError('monitor_expected_array')
            result.append(value)
            self.buffer = self.buffer[end:]
        return result

    def finish(self):
        if self.buffer.strip():
            raise ValueError('monitor_incomplete_document')


class RouteHistory:
    def __init__(self, source, sink, pid):
        self.source, self.sink, self.pid = source, sink, str(pid)
        self.objects, self.identity = {}, None
        self.error, self.batches = None, 0

    def fail(self, reason):
        if self.error is None:
            self.error = str(reason)

    def observe(self, changes):
        initial = self.batches == 0
        # pw-dump arrays are changed-object batches, not event time order.
        # Resolve new output nodes even when their Link precedes their Node.
        staged_outputs = {}
        for item in changes:
            props = (item.get('info') or {}).get('props', {})
            if (item['id'] not in self.objects and item.get('type') == 'PipeWire:Interface:Node'
                    and props.get('media.class') == 'Stream/Output/Audio'):
                staged_outputs[item['id']] = props
        self.batches += 1
        for item in changes:
            id = item['id']
            if 'info' in item and item['info'] is None:
                self.objects.pop(id, None)
            else:
                old = self.objects.setdefault(id, {})
                for key, value in item.items():
                    if key == 'info':
                        old.setdefault('info', {}).update(deepcopy(value))
                    else:
                        old[key] = deepcopy(value)
            # Retain a bad intermediate event even if the same batch restores it.
            if not initial:
                self._inspect(staged_outputs=staged_outputs, complete=False)
        self._inspect()

    def _inspect(self, *, staged_outputs=None, complete=True):
        try:
            current = self._route(staged_outputs=staged_outputs, complete=complete)
            if self.identity is None:
                self.identity = current
            elif self.identity != current:
                raise RuntimeError('route_identity_changed')
        except (RuntimeError, KeyError, TypeError) as exc:
            self.fail(str(exc))

    def _route(self, *, staged_outputs=None, complete=True):
        nodes = {id: obj['info']['props'] for id, obj in self.objects.items()
                 if obj.get('type') == 'PipeWire:Interface:Node'}
        states = {id: self.objects[id]['info'].get('state') for id in nodes}
        nodes = {**(staged_outputs or {}), **nodes}
        core = [obj['info']['cookie'] for obj in self.objects.values()
                if obj.get('type') == 'PipeWire:Interface:Core']
        if len(core) != 1:
            raise RuntimeError('core_unconfirmed')
        endpoints = {}
        for name, kind in ((self.source, 'Audio/Source'), (self.sink, 'Audio/Sink')):
            found = [(id, p) for id, p in nodes.items() if p.get('node.name') == name]
            if len(found) != 1 or found[0][1].get('media.class') != kind:
                raise RuntimeError('endpoint_missing_or_ambiguous')
            id, props = found[0]
            endpoints[name] = (id, props['object.serial'])
        streams = {id: p for id, p in nodes.items() if p.get('application.name') == 'VRChat.exe'}
        if not streams or any(str(p.get('application.process.id')) != self.pid for p in streams.values()):
            raise RuntimeError('vrchat_pid_unconfirmed')
        inputs = {id: p for id, p in streams.items() if p.get('media.class') == 'Stream/Input/Audio'}
        outputs = {id for id, p in streams.items() if p.get('media.class') == 'Stream/Output/Audio'}
        if not inputs:
            raise RuntimeError('vrchat_stream_missing')
        links = [obj['info'] for obj in self.objects.values() if obj.get('type') == 'PipeWire:Interface:Link']
        source_id, sink_id = endpoints[self.source][0], endpoints[self.sink][0]
        for id in inputs:
            incoming = [link for link in links if link['input-node-id'] == id]
            if not incoming or any(link['output-node-id'] != source_id or link.get('state') != 'active' for link in incoming):
                raise RuntimeError('microphone_route_unconfirmed')
        for id in outputs:
            outgoing = [link for link in links if link['output-node-id'] == id]
            # VRChat opens/closes playback streams for menu/world sounds. An
            # idle stream may pause and unlink; its microphone must stay live.
            # A newly created playback link negotiates before becoming active.
            # For playback we prove destination isolation, not uninterrupted
            # rendering; only the microphone requires continuously active links.
            inactive = states.get(id) in ('creating', 'suspended', 'idle')
            if (complete and not outgoing and not inactive) or any(
                    link['input-node-id'] != sink_id or
                    link.get('state') not in ('init', 'negotiating', 'allocating', 'paused', 'active')
                    for link in outgoing):
                raise RuntimeError('playback_route_unconfirmed')
        if any(link['output-node-id'] not in outputs for link in links if link['input-node-id'] == sink_id):
            raise RuntimeError('playback_sink_not_isolated')
        return {'core': core[0], 'endpoints': endpoints,
                'inputs': sorted((id, p['object.serial']) for id, p in inputs.items()), 'pid': self.pid}

    def check(self):
        if self.error:
            raise RuntimeError(self.error)
        if self.identity is None:
            raise RuntimeError('monitor_not_ready')
        return {'valid': True, 'identity': self.identity, 'batches': self.batches}


class RouteWatch:
    def __init__(self, source, sink, pid, output):
        self.history = RouteHistory(source, sink, pid)
        self.lock, self.ready, self.stopping = Lock(), Event(), Event()
        self.log = output.open('w')
        self.stderr = output.with_suffix('.stderr.log').open('w')
        self.process = None
        self.thread = None
        self.termination_requested = False
        try:
            self.process = subprocess.Popen(['pw-dump', '--monitor', '--no-colors'],
                                            stdout=subprocess.PIPE, stderr=self.stderr)
            self.thread = Thread(target=self._read, daemon=True)
            self.thread.start()
            if not self.ready.wait(10):
                raise RuntimeError('monitor_start_timeout')
            self.check()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                original.add_note('monitor cleanup: '+repr(cleanup))
            raise

    def _read(self):
        parser, decoder = JSONArrays(), codecs.getincrementaldecoder('utf-8')()
        try:
            while chunk := self.process.stdout.read1(65536):
                for changes in parser.feed(decoder.decode(chunk)):
                    with self.lock:
                        self.history.observe(changes)
                        # Preserve relevant events without recording unrelated node properties.
                        types = ('PipeWire:Interface:Core', 'PipeWire:Interface:Node', 'PipeWire:Interface:Link')
                        self.log.write(json.dumps({'time_ns': time.monotonic_ns(),
                            'changes': [self._event(x) for x in changes if x.get('type') in types or 'type' not in x],
                            'error': self.history.error})+'\n')
                        self.log.flush()
                    self.ready.set()
            parser.feed(decoder.decode(b'', final=True))
            parser.finish()
            if not self.stopping.is_set():
                raise RuntimeError('monitor_ended')
        except BaseException as exc:
            with self.lock:
                self.history.fail(str(exc))
            self.ready.set()

    @staticmethod
    def _event(obj):
        result = {k: obj[k] for k in ('id', 'type') if k in obj}
        info = obj.get('info')
        result['info'] = None if info is None else {k: info[k] for k in (
            'cookie', 'state', 'output-node-id', 'input-node-id') if k in info}
        if info and 'props' in info:
            result['info']['props'] = {k: v for k, v in info['props'].items() if k in (
                'node.name', 'object.serial', 'media.class', 'application.name', 'application.process.id')}
        return result

    def check(self):
        with self.lock:
            if self.process.poll() is not None or not self.thread.is_alive():
                self.history.fail('monitor_ended')
            return self.history.check()

    def finish(self):
        """Drain and validate received events before a caller declares success.

        pw-dump can coalesce changes and exposes no sync command/heartbeat. This
        is deliberately NOT a guarantee that every transient link event arrived.
        A healthy last snapshot alone is never used to clear a latched failure.
        """
        try:
            self.check()
        finally:
            self.close()
        with self.lock:
            if self.process.returncode not in (0, -signal.SIGTERM):
                self.history.fail('monitor_exit_'+str(self.process.returncode))
            return {**self.history.check(), 'scope': 'received_pipewire_changes',
                    'terminal_sync': False, 'heartbeat': False,
                    'termination_requested': self.termination_requested,
                    'exit_code': self.process.returncode}

    def close(self):
        """Cleanup only; callers need finish(), not close(), to validate a run."""
        if self.stopping.is_set():
            return
        if self.process is not None and (self.process.poll() is not None or
                                         (self.thread is not None and not self.thread.is_alive())):
            with self.lock:
                self.history.fail('monitor_ended')
        self.stopping.set()
        try:
            if self.process is not None:
                if self.process.poll() is None:
                    self.termination_requested = True
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
                else:
                    with self.lock:
                        self.history.fail('monitor_ended')
                if self.thread:
                    self.thread.join(3)
                    if self.thread.is_alive():
                        raise RuntimeError('monitor_reader_cleanup_failed')
                self.process.stdout.close()
        finally:
            self.log.close()
            self.stderr.close()
