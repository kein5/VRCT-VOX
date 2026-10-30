"""Lifecycle and hostile control peers without a model or audio device."""
import json
import subprocess
import sys
import time

import pytest

from models.audio_routing.source_bridge import Endpoint
from models.voice_conversion import direct_voice, isolated
from models.voice_conversion.router_protocol import BASE_STATE
from tools.voice_acceptance import wait_for

SOURCE = Endpoint(1, 2, 'test.source', 'Audio/Source')
OPTIONS = dict(runtime='/seed', reference='/ref.wav')
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux isolated transport')


@pytest.mark.parametrize('mode', ['ready', 'pending', 'invalid', 'stale', 'oversize', 'stall', 'exit', 'cleanup', 'ignore_stop'])
def test_isolated_owner_reaps_and_rejects_bad_control_peer(monkeypatch, mode):
    monkeypatch.setattr(direct_voice, 'create_worker_process', lambda options: object())
    children = []
    script = '''
import json,sys,os,select,time
mode=sys.argv[1];state=json.loads(sys.argv[2])
request=json.loads(sys.stdin.buffer.readline())
assert set(request)=={'kind','source','options'} and request['kind']=='start'
state.update(requested=True,active=mode!='pending',pending=mode=='pending',state='preparing' if mode=='pending' else 'ready')
while True:
 if mode=='exit':sys.exit(1)
 if mode=='invalid':state['active']=1
 if mode=='oversize':sys.stdout.write('x'*32768);sys.stdout.flush();time.sleep(3)
 if mode=='stall':time.sleep(3)
 print(json.dumps(dict(state,kind='health',sent_ns=1 if mode=='stale' else time.monotonic_ns())),flush=True)
 if select.select([sys.stdin],[],[],.03)[0]:
  if not os.read(0,1):
   if mode=='ignore_stop':time.sleep(20)
   sys.exit(2 if mode=='cleanup' else 0)
'''
    def launch():
        child = subprocess.Popen([sys.executable, '-u', '-c', script, mode, json.dumps(BASE_STATE)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        children.append(child)
        return child
    monkeypatch.setattr(isolated, '_launch', launch)
    process = isolated.IsolatedVCProcess(OPTIONS)
    try:
        process.start(source=SOURCE)
        if mode in ('ready', 'cleanup', 'ignore_stop'):
            wait_for(lambda: process.health()['active'], timeout=3)
        elif mode == 'pending':
            wait_for(lambda: children, timeout=3)
            time.sleep(.08)
            assert process.health()['pending'] and not process.health()['active']
        else:
            wait_for(lambda: process.health()['error'], timeout=3)
            assert not process.health()['active']
        before = time.monotonic()
        process.stop()
        assert time.monotonic()-before < .1
        assert process.close(timeout=3) is (mode not in ('cleanup', 'ignore_stop', 'oversize'))
        assert children and all(child.poll() is not None for child in children)
        assert not process.health()['active'] and not process.health()['pending']
        with pytest.raises(RuntimeError, match='vc_single_use'):
            process.start(source=SOURCE)
    finally:
        process.close(timeout=3)


def test_relative_paths_are_pinned_before_worker_cwd_changes(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    received = []
    monkeypatch.setattr(direct_voice, 'create_worker_process', lambda options: received.append(options.copy()))
    process = isolated.IsolatedVCProcess(dict(runtime='runtime', reference='ref.wav'))
    assert process.options == dict(runtime=str(tmp_path/'runtime'), reference=str(tmp_path/'ref.wav'))
    assert received == [process.options]
