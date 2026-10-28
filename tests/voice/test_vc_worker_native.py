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


@pytest.mark.parametrize('mode', ['normal', 'kill', 'thread', 'supervisor'])
def test_worker_lifetime_is_bound_to_owner_and_supervisor(tmp_path, mode):
    helper = compile_helper(tmp_path, 'native/vc-worker/main.c')
    interpreter = tmp_path / 'python'
    interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$$"\nexec ' + shutil.which('sleep') + ' 30\n')
    interpreter.chmod(0o700)
    script = '''
import os, subprocess, sys, threading, time
mode, helper, interpreter = sys.argv[1:]
leave = threading.Event()
def launch():
    fd = os.pidfd_open(threading.get_native_id(), os.O_EXCL)
    try:
        child = subprocess.Popen([helper, str(os.getpid()), str(fd), interpreter,
            '/engine', '/assets', '/reference.wav', 'a'*32], pass_fds=(fd,), stdout=subprocess.PIPE)
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
    owner = subprocess.Popen([sys.executable, '-u', '-c', script, mode, str(helper), str(interpreter)],
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
