"""Own fixed speech.cpp children without coupling audio callbacks to inference."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import select
import socket
import stat
import subprocess
from runtime_paths import resource_root, external_process_env
from threading import Event, Lock, Thread, Timer, current_thread, get_native_id
import time

from .settings import PROFILES

ROOT=resource_root()
BUNDLE=ROOT/'build/speechcpp'
HELPER=ROOT/'build/vrct-vc-worker'
START_TIMEOUT=120.0
HASHES={'linux-x64-cpu':'394fd7c0636143fa96fc961af55f1bcdcf71fa557e4c210e231eb253a97353d8',
        'linux-x64-vulkan':'800e9bae0057a7ce2b63dde01a71bf83653ffbd70eb83f8bea3e8fd944f678e7'}
READY=re.compile(rb'API at http://127\.0\.0\.1:([0-9]{1,5})/v1(?:;|$)')
ANSI=re.compile(rb'\x1b\[[0-9;]*m')


def bundled_binary():
    """Integrity check for the fixed package resource; no executable PATH lookup."""
    try:
        meta=BUNDLE/'bundle.json'; binary=BUNDLE/'speech'
        if (BUNDLE.is_symlink() or not stat.S_ISREG(meta.lstat().st_mode) or meta.stat().st_size>65536
                or not stat.S_ISREG(binary.lstat().st_mode) or not os.access(binary,os.X_OK)):
            raise ValueError()
        data=json.loads(meta.read_text())
        if type(data['schema']) is not int or data['schema']!=1 or data['version']!='0.9.0':
            raise ValueError()
        expected=HASHES[data['variant']]
        digest=hashlib.sha256()
        with binary.open('rb') as source:
            while block:=source.read(1024*1024): digest.update(block)
        if digest.hexdigest()!=expected: raise ValueError()
        return binary.resolve()
    except (OSError,ValueError,TypeError,KeyError):
        raise RuntimeError('speech_bundle_missing_or_invalid') from None


class _Failure(Exception):
    pass


def _json(port, path, deadline):
    """Numeric loopback only, with a total request deadline even for slow headers."""
    remaining=min(.5,deadline-time.monotonic())
    if remaining<=0: raise _Failure('speech_server_start_timeout')
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=remaining)
    expired=Event(); sock=None
    def interrupt():
        expired.set()
        if sock is not None:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
    timer=Timer(remaining,interrupt);timer.daemon=True;timer.start()
    try:
        conn.connect();sock=conn.sock
        if expired.is_set(): raise _Failure('speech_server_readiness')
        conn.request('GET',path)
        response=conn.getresponse()
        if response.status!=200: raise _Failure('speech_server_readiness')
        body=response.read(65537)
        if len(body)>65536 or expired.is_set(): raise _Failure('speech_server_readiness')
        return json.loads(body)
    except (OSError,ValueError,http.client.HTTPException):
        raise _Failure('speech_server_readiness') from None
    finally:
        timer.cancel();conn.close();timer.join(.5)


class SpeechServer:
    def __init__(self,profile,options,*,binary=None,helper=None,on_end=None):
        if profile not in PROFILES:
            raise ValueError('speech_server_profile_invalid')
        self.profile,self.options=profile,dict(options)
        self.binary,self.helper=binary,Path(helper) if helper else HELPER
        self.on_end=on_end
        self._lock,self._stop=Lock(),Event()
        self._thread=self._child=None
        self._cleanup_ok=True
        self._state=dict(state='stopped',base_url=None,error_code=None)

    def health(self):
        with self._lock: return dict(self._state)

    def start(self):
        with self._lock:
            if self._thread is not None or self._stop.is_set():
                raise RuntimeError('speech_server_single_use')
            self._state.update(state='preparing')
            self._thread=Thread(target=self._run,name='vrct-speech-'+self.profile,daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._stop.set();self._state['base_url']=None
            if self._state['state'] in ('preparing','ready'):
                self._state['state']='stopping'

    def close(self,timeout=3):
        self.stop()
        thread=self._thread
        if thread and thread is not current_thread(): thread.join(max(0,timeout))
        return (thread is None or not thread.is_alive()) and self._cleanup_ok

    def _launch(self,binary):
        owner=os.pidfd_open(get_native_id(),os.O_EXCL)
        try:
            row=self.options
            args=[str(self.helper),str(os.getpid()),str(owner),str(binary),'speech-server',
                  row['model'],row['vad_model'],row['voice_file'],row['device']]
            return subprocess.Popen(args,pass_fds=(owner,),stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,bufsize=0,
                env=dict(external_process_env(),NO_COLOR='1'))
        finally: os.close(owner)

    def _ready(self,port,deadline):
        if _json(port,'/health',deadline)!={'status':'ok'}:
            raise _Failure('speech_server_readiness')
        if self._stop.is_set(): return
        models=_json(port,'/v1/models',deadline)
        try: tasks=[row['speech']['task'] for row in models['data']]
        except (KeyError,TypeError): raise _Failure('speech_server_model_tasks') from None
        expected=['recognition','detection'] if self.profile=='asr' else ['synthesis']
        if sorted(tasks)!=sorted(expected): raise _Failure('speech_server_model_tasks')
        with self._lock:
            if not self._stop.is_set() and self._child.poll() is None:
                self._state.update(state='ready',base_url=f'http://127.0.0.1:{port}')

    def _run(self):
        failure=None
        try:
            deadline=time.monotonic()+START_TIMEOUT
            binary=Path(self.binary) if self.binary else bundled_binary()
            if self._stop.is_set(): return
            self._child=self._launch(binary)
            os.set_blocking(self._child.stderr.fileno(),False)
            pending=bytearray()
            while not self._stop.is_set():
                if self._child.poll() is not None:
                    raise _Failure('speech_server_exited')
                if self.health()['state']!='ready' and time.monotonic()>=deadline:
                    raise _Failure('speech_server_start_timeout')
                if not select.select([self._child.stderr],[],[],.05)[0]: continue
                data=os.read(self._child.stderr.fileno(),8192)
                if not data: continue
                pending.extend(data)
                while b'\n' in pending:
                    line,_,tail=pending.partition(b'\n');pending=bytearray(tail)
                    if len(line)>65536: raise _Failure('speech_server_protocol')
                    if self.health()['state']=='ready': continue
                    matched=READY.search(ANSI.sub(b'',line))
                    if matched:
                        port=int(matched[1])
                        if not 1<=port<=65535: raise _Failure('speech_server_protocol')
                        self._ready(port,deadline)
                if len(pending)>65536: raise _Failure('speech_server_protocol')
        except _Failure as exc:
            failure=str(exc)
        except Exception:
            failure='speech_server_launch_failed'
        finally:
            if self._child is not None:
                try:
                    if self._child.poll() is None:
                        self._child.terminate()
                        try: self._child.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            self._child.kill();self._child.wait(timeout=.5)
                except (OSError,subprocess.TimeoutExpired): self._cleanup_ok=False
                self._child.stderr.close()
            with self._lock:
                if not self._cleanup_ok: failure='speech_server_cleanup_unconfirmed'
                elif self._stop.is_set(): failure=None
                self._state.update(state='failed' if failure else 'stopped',base_url=None,error_code=failure)
            if self.on_end:
                try: self.on_end(self.profile)
                except Exception:
                    with self._lock:
                        self._state.update(state='failed',error_code='speech_server_notification_failed')


class SpeechServers:
    def __init__(self,*,on_end=None):
        self._lock=Lock();self._closed=False;self.on_end=on_end
        self._owners={name:None for name in PROFILES}
        self._generations={name:0 for name in PROFILES}

    def _profile(self,profile):
        if profile not in PROFILES: raise ValueError('speech_server_profile_invalid')

    def state(self):
        with self._lock:
            return {name:dict(owner.health() if owner else dict(state='stopped',base_url=None,error_code=None),
                              generation=self._generations[name]) for name,owner in self._owners.items()}

    def binding(self,profile):
        self._profile(profile)
        with self._lock:
            owner=self._owners[profile]
            state=owner.health() if owner else {}
            if self._closed or state.get('state')!='ready' or not state.get('base_url'):
                raise RuntimeError('speech_server_not_ready')
            return state['base_url']

    def start(self,profile,options,expected_generation):
        self._profile(profile)
        with self._lock:
            if self._closed: raise RuntimeError('speech_server_closed')
            if type(expected_generation) is not int or expected_generation!=self._generations[profile]:
                raise RuntimeError('speech_server_stale_start')
            old=self._owners[profile]
            if old and (old.health()['state'] in ('ready','preparing') or not old.close(timeout=0)):
                raise RuntimeError('speech_server_busy')
            def ended(name):
                with self._lock:
                    if self._owners[name] is not owner: return
                    self._generations[name]+=1
                if self.on_end: self.on_end(name)
            owner=SpeechServer(profile,options,on_end=ended)
            self._owners[profile]=owner;self._generations[profile]+=1
            owner.start()

    def stop(self,profile):
        self._profile(profile)
        with self._lock:
            self._generations[profile]+=1
            owner=self._owners[profile]
            if owner: owner.stop()

    def close(self,timeout=3):
        deadline=time.monotonic()+timeout
        with self._lock:
            self._closed=True
            owners=[owner for owner in self._owners.values() if owner]
            for name in PROFILES: self._generations[name]+=1
            for owner in owners: owner.stop()
        results=[owner.close(timeout=max(0,deadline-time.monotonic())) for owner in owners]
        return all(results)
