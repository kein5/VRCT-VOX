"""Owned fake HTTP children exercise real Linux process lifetime; no models/GPU."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time

import psutil
import pytest

from test_source_bridge_native import compile_helper
from tools.voice_acceptance import wait_for

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux speech ownership')


def modules():
    return (importlib.import_module('models.speech_server.settings'),
            importlib.import_module('models.speech_server.runtime'))


@pytest.fixture
def fake(tmp_path):
    helper = compile_helper(tmp_path, 'native/vc-worker/main.c')
    binary = tmp_path/'speech'
    binary.write_text('#!'+sys.executable+'''\n
import http.server,json,sys,time
from pathlib import Path
mode=Path(sys.argv[2]).stem
if mode=='crash': sys.exit(1)
if mode=='wait': time.sleep(30); sys.exit(0)
if mode=='overflow': sys.stderr.write('x'*70000); sys.stderr.flush(); time.sleep(30)
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if mode=='badhealth': self.send_error(500); return
        tasks=(['recognition','detection'] if mode=='asr' else ['synthesis'])
        if mode=='wrong': tasks=[]
        payload=({'status':'ok'} if self.path=='/health' else
                 {'data':[{'id':task,'speech':{'task':task}} for task in tasks]})
        body=json.dumps(payload).encode()
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
server=http.server.HTTPServer(('127.0.0.1',0),Handler)
sys.stderr.write('    API at http://127.0.0.1:%d/v1; Ctrl-C stops the server\\n'%server.server_port)
sys.stderr.flush()
server.serve_forever()
''')
    binary.chmod(0o700)
    return binary, helper


def options(tmp_path, name='tts', profile='japanese'):
    settings, _ = modules()
    model = tmp_path/(name+'.gguf')
    model.write_bytes(b'GGUF'+b'\0'*16)
    value = settings.normalize_settings({})
    value['profiles'][profile]['model'] = str(model)
    if profile == 'asr':
        vad = tmp_path/'vad.gguf'; vad.write_bytes(b'GGUF'+b'\0'*16)
        value['profiles'][profile]['vad_model'] = str(vad)
    return settings.start_options(value, profile)


def gone(child):
    try: return not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess: return True


def test_choices_persist_without_recording_process_intent():
    settings, _ = modules()
    default = settings.normalize_settings({})
    assert default == {'version':1, 'profiles':{name:dict(model='',vad_model='',voice_file='',device='auto')
                                              for name in ('japanese','multilingual','asr')}}
    default['profiles']['asr']['model'] = '/absent/user-choice.gguf'
    assert settings.normalize_settings(default) == default


@pytest.mark.parametrize('value', [None, {'version':True}, {'active':True}, {'profiles':{'unknown':{}}},
    {'profiles':{'japanese':{'device':'cuda:0'}}}, {'profiles':{'japanese':{'model':'bad\npath'}}},
    {'profiles':{'japanese':{'vad_model':'wrong.gguf'}}}, {'profiles':{'asr':{'voice_file':'wrong.gguf'}}}])
def test_invalid_settings_rejected(value):
    with pytest.raises(ValueError, match='speech_server_'):
        modules()[0].normalize_settings(value)


@pytest.mark.parametrize('fault', ['absent','alias','magic','vad'])
def test_start_requires_local_gguf_files(tmp_path, fault):
    settings, _ = modules(); value=settings.normalize_settings({})
    if fault=='absent': pass
    elif fault=='alias': value['profiles']['japanese']['model']='qwen3-tts-0.6b'
    elif fault=='magic':
        path=tmp_path/'bad.gguf';path.write_bytes(b'BAD!');value['profiles']['japanese']['model']=str(path)
    else:
        path=tmp_path/'asr.gguf';path.write_bytes(b'GGUF');value['profiles']['asr']['model']=str(path)
    with pytest.raises(ValueError, match='speech_server_'):
        settings.start_options(value, 'asr' if fault=='vad' else 'japanese')


@pytest.mark.parametrize('profile,model', [('japanese','tts'),('multilingual','tts'),('asr','asr')])
def test_server_becomes_ready_then_stops_and_reaps_only_its_child(tmp_path, fake, profile, model):
    _, runtime=modules(); binary,helper=fake; ended=[]
    server=runtime.SpeechServer(profile,options(tmp_path,model,profile),binary=binary,helper=helper,on_end=ended.append)
    try:
        assert server.health()['state']=='stopped'
        server.start()
        wait_for(lambda: server.health()['state'] in ('ready','failed'),timeout=4)
        assert server.health()['state']=='ready',server.health()
        assert server.health()['base_url'].startswith('http://127.0.0.1:')
        parent=psutil.Process(server._child.pid); children=parent.children()
        assert len(children)==1
        server.stop()
        assert server.health()['base_url'] is None
        assert server.close(timeout=3)
        assert all(gone(p) for p in [parent,*children])
        assert server.health()['state']=='stopped'
        assert ended==[profile]
    finally: server.close()


def test_stop_during_load_cannot_later_become_ready(tmp_path,fake):
    _, runtime=modules();binary,helper=fake
    server=runtime.SpeechServer('japanese',options(tmp_path,'wait'),binary=binary,helper=helper)
    try:
        server.start();wait_for(lambda: server._child is not None,timeout=3)
        child=psutil.Process(server._child.pid)
        began=time.monotonic();server.stop()
        assert server.close(timeout=3)
        assert time.monotonic()-began<3
        assert gone(child) and server.health()['state']=='stopped'
        with pytest.raises(RuntimeError):server.start()
    finally:server.close()


@pytest.mark.parametrize('mode,code', [('wrong','speech_server_model_tasks'),
    ('overflow','speech_server_protocol'),('crash','speech_server_exited'),
    ('badhealth','speech_server_readiness'),('wait','speech_server_start_timeout')])
def test_failed_start_is_bounded_and_does_not_publish_endpoint(tmp_path,fake,monkeypatch,mode,code):
    _,runtime=modules();binary,helper=fake
    monkeypatch.setattr(runtime,'START_TIMEOUT',.4 if mode=='wait' else 3)
    server=runtime.SpeechServer('japanese',options(tmp_path,mode),binary=binary,helper=helper)
    try:
        server.start();wait_for(lambda:server.health()['state']=='failed',timeout=4)
        assert server.health()['error_code']==code,server.health()
        assert server.health()['base_url'] is None
        assert server.close()
        assert server._child is None or server._child.poll() is not None
    finally:server.close()


def test_ready_server_death_invalidates_endpoint(tmp_path,fake):
    _,runtime=modules();binary,helper=fake;ended=[]
    server=runtime.SpeechServer('japanese',options(tmp_path),binary=binary,helper=helper,on_end=ended.append)
    try:
        server.start();wait_for(lambda:server.health()['state']=='ready',timeout=4)
        owned=psutil.Process(server._child.pid).children()[0];owned.kill()
        wait_for(lambda:server.health()['state']=='failed',timeout=4)
        assert server.health()['base_url'] is None
        assert ended==['japanese']
    finally:server.close()


def test_hub_rejects_stale_start_and_never_reuses_stopped_endpoint(tmp_path,fake,monkeypatch):
    _,runtime=modules();binary,helper=fake;real=runtime.SpeechServer
    monkeypatch.setattr(runtime,'SpeechServer',lambda *a,**kw:real(*a,binary=binary,helper=helper,**kw))
    hub=runtime.SpeechServers();opts=options(tmp_path)
    try:
        generation=hub.state()['japanese']['generation']
        hub.stop('japanese')
        with pytest.raises(RuntimeError,match='stale'):hub.start('japanese',opts,generation)
        hub.start('japanese',opts,hub.state()['japanese']['generation'])
        wait_for(lambda:hub.state()['japanese']['state']=='ready',timeout=4)
        assert hub.binding('japanese').startswith('http://127.0.0.1:')
        with pytest.raises(RuntimeError,match='busy'):hub.start('japanese',opts,hub.state()['japanese']['generation'])
        hub.stop('japanese')
        with pytest.raises(RuntimeError,match='not_ready'):hub.binding('japanese')
        assert hub.close()
        with pytest.raises(RuntimeError,match='closed'):hub.start('japanese',opts,hub.state()['japanese']['generation'])
    finally:hub.close()


def test_bundle_selection_rejects_missing_corrupt_or_unpinned_binary(tmp_path,monkeypatch):
    _,runtime=modules();monkeypatch.setattr(runtime,'BUNDLE',tmp_path)
    with pytest.raises(RuntimeError,match='speech_bundle_'):runtime.bundled_binary()
    (tmp_path/'bundle.json').write_text(json.dumps({'schema':1,'version':'0.9.0','variant':'linux-x64-cpu'}))
    (tmp_path/'speech').write_bytes(b'not the pinned binary');(tmp_path/'speech').chmod(0o700)
    with pytest.raises(RuntimeError,match='speech_bundle_'):runtime.bundled_binary()
