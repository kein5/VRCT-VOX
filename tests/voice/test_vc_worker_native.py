"""The fixed external worker must not outlive its creating control thread."""
import select
import shutil
import subprocess
import sys

import psutil
import pytest

from test_source_bridge_native import compile_helper
from tools.voice_acceptance import wait_for

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux worker supervisor')


@pytest.mark.parametrize('mode, expected', [
    ('router', ['-u', '-m', 'models.voice_conversion.router_worker']),
    ('router-frozen', ['--voice-router-worker']),
])
def test_router_supervisor_has_only_fixed_entry_points(tmp_path, mode, expected):
    import json
    import os
    import threading
    helper = compile_helper(tmp_path, 'native/vc-worker/main.c')
    interpreter = tmp_path/'capture-args'
    interpreter.write_text('#!'+sys.executable+'\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\n')
    interpreter.chmod(0o700)
    owner = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
    try:
        args = [str(helper), str(os.getpid()), str(owner), str(interpreter)]
        result = subprocess.run([*args, mode], pass_fds=(owner,), capture_output=True, timeout=3, check=True)
        assert json.loads(result.stdout) == expected
        invalid = subprocess.run([*args, 'arbitrary-module'], pass_fds=(owner,), capture_output=True, timeout=3)
        assert invalid.returncode == 2 and not invalid.stdout
    finally:
        os.close(owner)


def test_rvc_supervisor_passes_only_fixed_module_and_explicit_settings(tmp_path):
    import json
    import os
    import threading
    helper = compile_helper(tmp_path, 'native/vc-worker/main.c')
    interpreter = tmp_path / 'capture-args'
    interpreter.write_text('#!' + sys.executable + '\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\n')
    interpreter.chmod(0o700)
    owner = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
    try:
        result = subprocess.run([str(helper), str(os.getpid()), str(owner), str(interpreter),
            '/engine', '/assets', '/voice.pth', 'a'*32, 'rvc', '/voice.index', '-3', '0.5'],
            pass_fds=(owner,), capture_output=True, timeout=3, check=True)
        assert json.loads(result.stdout) == ['-u', '-m', 'integrations.rvc.live_worker',
            '--engine', '/engine', '--assets', '/assets', '--model', '/voice.pth', '--session',
            'a'*32, '--index', '/voice.index', '--pitch', '-3', '--index-rate', '0.5']
    finally:
        os.close(owner)


@pytest.mark.parametrize('engine', ['seed-vc', 'rvc', 'router', 'router-frozen', 'speech-server'])
@pytest.mark.parametrize('mode', ['normal', 'kill', 'thread', 'supervisor'])
def test_worker_lifetime_is_bound_to_owner_and_supervisor(tmp_path, mode, engine):
    helper = compile_helper(tmp_path, 'native/vc-worker/main.c')
    interpreter = tmp_path / 'python'
    interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$$"\nexec ' + shutil.which('sleep') + ' 30\n')
    interpreter.chmod(0o700)
    script = '''
import os, subprocess, sys, threading, time
mode, helper, interpreter, engine = sys.argv[1:]
leave = threading.Event()
def launch():
    fd = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
    try:
        args = ([engine,'/model.gguf','','','auto'] if engine=='speech-server' else
                [engine] if engine.startswith('router') else
                ['/engine', '/assets', '/reference.wav', 'a'*32] + (['rvc', '', '0', '0'] if engine == 'rvc' else []))
        child = subprocess.Popen([helper, str(os.getpid()), str(fd), interpreter, *args], pass_fds=(fd,), stdout=subprocess.PIPE)
    finally:
        os.close(fd)
    print(child.stdout.readline().decode().strip(), flush=True)
    if mode == 'thread': leave.wait()
    if mode == 'supervisor':
        input()
        child.kill()
        child.wait(timeout=2)
        time.sleep(30)
if mode == 'thread':
    thread = threading.Thread(target=launch)
    thread.start()
    input()
    leave.set()
    thread.join()
    time.sleep(30)
else:
    launch()
    input()
'''
    owner = subprocess.Popen([sys.executable, '-u', '-c', script, mode, str(helper), str(interpreter), engine],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    child = None
    try:
        assert select.select([owner.stdout], [], [], 3)[0], 'worker not launched'
        child = psutil.Process(int(owner.stdout.readline()))
        if mode == 'kill':
            owner.kill()
        else:
            owner.stdin.write(b'go\n')
            owner.stdin.flush()
        def ended():
            try:
                return not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                return True
        wait_for(ended, timeout=3, code='worker_outlived_owner')
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=3)
        owner.stdin.close()
        owner.stdout.close()
        if child is not None:
            try:
                if child.is_running():
                    child.kill()
            except psutil.NoSuchProcess:
                pass


def test_speech_supervisor_fixes_host_port_and_limits_arguments(tmp_path):
    import json
    import os
    import threading
    helper=compile_helper(tmp_path,'native/vc-worker/main.c')
    binary=tmp_path/'capture-args'
    binary.write_text('#!'+sys.executable+'\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\n')
    binary.chmod(0o700)
    fd=os.pidfd_open(threading.get_native_id(),os.O_EXCL)
    try:
        args=[str(helper),str(os.getpid()),str(fd),str(binary),'speech-server']
        result=subprocess.run([*args,'/model.gguf','/vad.gguf','/voice.gguf','cpu'],pass_fds=(fd,),capture_output=True,timeout=3,check=True)
        assert json.loads(result.stdout)==['serve','/model.gguf','/vad.gguf','--host','127.0.0.1','--port','0','--device','cpu','--add-voice','custom=/voice.gguf']
        for values in [('named-model','','','auto'),('/model','','','--host'),('/model','vad','','auto'),('/model','','voice','auto')]:
            denied=subprocess.run([*args,*values],pass_fds=(fd,),capture_output=True,timeout=3)
            assert denied.returncode==2 and not denied.stdout
    finally:os.close(fd)
