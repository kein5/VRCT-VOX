"""Own fixed speech.cpp children without coupling audio callbacks to inference."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
from runtime_paths import resource_root, external_process_env
from threading import Event, Lock, Thread, Timer, current_thread, get_native_id
import time

from .settings import PROFILES
from .low_latency import LowLatencyStandby
from .warmup import warm_up
from models.failure_report import report_failure
from models.owned_child import launch_owned, wait_readable
from models.tts.listener_monitor import listener_monitors
from models.tts.speechcpp_tts import CancelToken

ROOT=resource_root()
BUNDLE=ROOT/'build/speechcpp'
HELPER=ROOT/'build/vrct-vc-worker'
START_TIMEOUT=120.0
# What a warm-up leaves of START_TIMEOUT, so it cannot be what fails the start.
WARM_UP_MARGIN=2.0
HASHES={'linux-x64-cpu':'7a9c6caa705f56bd52db1fa1a2d8317e5e07da6a291d2dfa37f4e9bb0e55654a',
        'linux-x64-vulkan':'410edfb9fd1e74112627d17a33ca0d30cb24ac88890f8fc3bcfb8e7a3ad8d1bc',
        'windows-x64-vulkan':'fa787d70ce3c9d83b11aacd06024d2bfa89fccf0e4e34995245ef0cd341981b7'}
READY=re.compile(rb'API at http://127\.0\.0\.1:([0-9]{1,5})/v1(?:;|$)')
ANSI=re.compile(rb'\x1b\[[0-9;]*m')
# speech.cpp prints a failure as "speech: <category>: ..." or "speech: <category> (<option>): ...".
# These two categories have a next step of their own for the user.
ENGINE_FAILURE=re.compile(rb'speech: (out_of_memory|device)(?::| \()')
ENGINE_FAILURES={b'out_of_memory':'speech_server_out_of_memory',b'device':'speech_server_device_failed'}
DEVICE_LINE=re.compile(r'(Vulkan[0-9]{1,2})\s+(igpu|gpu)\s+(.+?),\s+[0-9.]+ GB,')
EXECUTABLE='speech.exe' if sys.platform=='win32' else 'speech'
# The loader reports a missing import as this NTSTATUS. Only vulkan-1.dll can be
# missing: the executable's other imports are all part of Windows.
DLL_NOT_FOUND=0xC0000135


def bundled_binary():
    """Integrity check for the fixed package resource; no executable PATH lookup."""
    try:
        meta=BUNDLE/'bundle.json'; binary=BUNDLE/EXECUTABLE
        if (BUNDLE.is_symlink() or not stat.S_ISREG(meta.lstat().st_mode) or meta.stat().st_size>65536
                or not stat.S_ISREG(binary.lstat().st_mode) or not os.access(binary,os.X_OK)):
            raise ValueError()
        data=json.loads(meta.read_text(encoding='utf-8'))
        if type(data['schema']) is not int or data['schema']!=1 or data['version']!='0.10.0':
            raise ValueError()
        expected=HASHES[data['variant']]
        digest=hashlib.sha256()
        with binary.open('rb') as source:
            while block:=source.read(1024*1024): digest.update(block)
        if digest.hexdigest()!=expected: raise ValueError()
        return binary.resolve()
    except (OSError,ValueError,TypeError,KeyError):
        raise RuntimeError('speech_bundle_missing_or_invalid') from None


def parse_devices(text):
    """The GPUs in `speech devices` output; the CPU is a choice of its own."""
    return [dict(name=found[1],kind=found[2],label=found[3])
            for found in map(DEVICE_LINE.match,text.splitlines()) if found]


def list_gpus():
    """The GPUs a server can be told to use, by the names the bundled speech.cpp prints."""
    try:
        done=subprocess.run([str(bundled_binary()),'devices'],stdin=subprocess.DEVNULL,capture_output=True,timeout=15,
            env=dict(external_process_env(),NO_COLOR='1'),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,RuntimeError,subprocess.SubprocessError):
        return []
    if done.returncode: return []
    return parse_devices((done.stdout+done.stderr).decode('utf-8','replace'))


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
        self._standby=None
        self._listener=None
        self._warmup=self._warm_token=None
        self._state=dict(state='stopped',base_url=None,error_code=None)

    def health(self):
        with self._lock:
            state=dict(self._state)
            if self._standby is not None: state['low_latency']=self._standby.health()
            return state

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
            token=self._warm_token
        if token is not None: token.cancel()

    def close(self,timeout=3):
        self.stop()
        thread=self._thread
        if thread and thread is not current_thread(): thread.join(max(0,timeout))
        return (thread is None or not thread.is_alive()) and self._cleanup_ok

    def _launch_windows(self,binary):
        # The same command line the Linux helper builds, under a kill-on-close job.
        row=self.options
        args=[str(binary),'serve',row['model']]
        if row['vad_model']: args.append(row['vad_model'])
        if row.get('diarization_model'): args.append(row['diarization_model'])
        args+=['--host','127.0.0.1','--port','0','--device',row['device']]
        if row['voice_file']: args+=['--add-voice','custom='+row['voice_file']]
        return launch_owned(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,env=dict(external_process_env(),NO_COLOR='1'),realtime=True)

    def _launch(self,binary):
        if sys.platform=='win32': return self._launch_windows(binary)
        owner=os.pidfd_open(get_native_id(),os.O_EXCL)
        try:
            row=self.options
            args=[str(self.helper),str(os.getpid()),str(owner),str(binary),'speech-server',
                  row['model'],row['vad_model'],row['voice_file'],row['device']]
            # The helper takes a diarization model as one more argument, only when there is one.
            if row.get('diarization_model'): args.append(row['diarization_model'])
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
        # A file in the diarization field that is another kind of model fails here.
        if self.profile=='asr' and self.options.get('diarization_model'): expected.append('diarization')
        if sorted(tasks)!=sorted(expected): raise _Failure('speech_server_model_tasks')
        if self.profile!='asr' and self._listener is None:
            self._listener=listener_monitors.own(('127.0.0.1',port),self._child)
        if self.options.get('low_latency'):
            speech=models['data'][0]['speech']
            if (self.profile!='japanese' or speech.get('architecture')!='irodori-tts'
                    or speech.get('device','CPU').lower()=='cpu'):
                raise _Failure('speech_server_low_latency_requires_gpu_irodori')
            self._standby=LowLatencyStandby(f'http://127.0.0.1:{port}')
        # The caller has to keep reading the child's output and watching for its
        # exit while the warm-up runs, and that can take many seconds.
        self._warmup=Thread(target=self._finish_start,args=(port,models['data'],deadline),
                            name='vrct-speech-warm-'+self.profile,daemon=True)
        self._warmup.start()

    def _finish_start(self,port,models,deadline):
        url=f'http://127.0.0.1:{port}'
        token=CancelToken()
        with self._lock:
            self._warm_token=token
            stopping=self._stop.is_set()
        if stopping: token.cancel()
        try: warm_up(self.profile,url,models,token,deadline-time.monotonic()-WARM_UP_MARGIN)
        except Exception: pass  # Only the first real request pays for this.
        if self._standby is not None and not self._stop.is_set(): self._standby.start()
        with self._lock:
            self._warm_token=None
            if not self._stop.is_set() and self._child.poll() is None:
                self._state.update(state='ready',base_url=url)

    def _end_warm_up(self):
        with self._lock: token=self._warm_token
        if token is not None: token.cancel()
        if self._warmup is not None: self._warmup.join(1)

    def _run(self):
        failure=None
        exit_error='speech_server_exited'
        try:
            deadline=time.monotonic()+START_TIMEOUT
            binary=Path(self.binary) if self.binary else bundled_binary()
            if self._stop.is_set(): return
            self._child=self._launch(binary)
            if sys.platform!='win32': os.set_blocking(self._child.stderr.fileno(),False)
            pending=bytearray()
            while not self._stop.is_set():
                exited=self._child.poll() is not None
                if not exited and self.health()['state']!='ready' and time.monotonic()>=deadline:
                    raise _Failure('speech_server_start_timeout')
                if not exited and not wait_readable(self._child.stderr,.05): continue
                if exited and sys.platform=='win32' and self._child.returncode==DLL_NOT_FOUND:
                    exit_error='speech_server_vulkan_missing'
                # A fast failure can exit before our first read. Drain a bounded
                # amount from the nonblocking pipe, including its final partial line.
                # Windows pipes block instead, so read only what select's stand-in saw.
                try:
                    data=(os.read(self._child.stderr.fileno(),65536 if exited else 8192)
                          if sys.platform!='win32' or wait_readable(self._child.stderr,0) else b'')
                except BlockingIOError: data=b''
                if not data and not exited: continue
                pending.extend(data)
                if exited and pending and not pending.endswith(b'\n'): pending.extend(b'\n')
                while b'\n' in pending:
                    line,_,tail=pending.partition(b'\n');pending=bytearray(tail)
                    if len(line)>65536: raise _Failure('speech_server_protocol')
                    line=ANSI.sub(b'',line).rstrip(b'\r')
                    # Only map the fixed engine's error category. Never publish
                    # raw stderr, which can contain local model paths or input.
                    # "device" is a GPU that cannot run the model: a driver that only
                    # maps Vulkan onto Direct3D 12 loads it and then fails to compute.
                    category=ENGINE_FAILURE.match(line)
                    if category and exit_error!='speech_server_out_of_memory':
                        exit_error=ENGINE_FAILURES[category[1]]
                    if exited or self.health()['state']=='ready': continue
                    matched=READY.search(line)
                    if matched:
                        port=int(matched[1])
                        if not 1<=port<=65535: raise _Failure('speech_server_protocol')
                        self._ready(port,deadline)
                if len(pending)>65536: raise _Failure('speech_server_protocol')
                if exited: raise _Failure(exit_error)
        except _Failure as exc:
            failure=str(exc)
        except RuntimeError as exc:
            # bundled_binary() names a missing or tampered bundle; keep that
            # distinct from a launch that failed for another reason.
            failure=str(exc) if str(exc)=='speech_bundle_missing_or_invalid' else 'speech_server_launch_failed'
        except Exception:
            failure='speech_server_launch_failed'
        finally:
            self._end_warm_up()
            if self._listener is not None:
                listener_monitors.forget(self._listener)
            if self._standby is not None and not self._standby.close(): self._cleanup_ok=False
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
            if failure: report_failure('speech_server',failure)
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
        # Unlike the public generation, a run does not change on Stop/end.
        self._runs={name:None for name in PROFILES}

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

    def current_run(self,profile):
        self._profile(profile)
        with self._lock:
            return self._runs[profile]

    def start(self,profile,options,expected_generation):
        self._profile(profile)
        with self._lock:
            if self._closed: raise RuntimeError('speech_server_closed')
            if type(expected_generation) is not int or expected_generation!=self._generations[profile]:
                raise RuntimeError('speech_server_stale_start')
            old=self._owners[profile]
            if old and (old.health()['state'] in ('ready','preparing') or not old.close(timeout=0)):
                raise RuntimeError('speech_server_busy')
            run=self._generations[profile]+1
            notified=False
            def ended(name):
                nonlocal notified
                with self._lock:
                    if self._owners[name] is not owner or notified: return
                    notified=True
                    self._generations[name]+=1
                if self.on_end: self.on_end(name,run)
            owner=SpeechServer(profile,options,on_end=ended)
            self._owners[profile]=owner;self._generations[profile]+=1
            self._runs[profile]=run
            owner.start()

    def stop(self,profile,generation=None,*,on_stop=None):
        # With a generation, stop only that exact start: a caller that owns one
        # run must not stop a newer server the user started after it ended.
        self._profile(profile)
        with self._lock:
            if generation is not None and generation!=self._generations[profile]:
                return False
            self._generations[profile]+=1
            owner=self._owners[profile]
            run=self._runs[profile]
            if owner: owner.stop()
        # Carry the stopped run across the unlocked notification; a new Start
        # or a late child cleanup must not turn this into another run's end.
        if on_stop: on_stop(profile,run)
        return True

    def close(self,timeout=3):
        deadline=time.monotonic()+timeout
        with self._lock:
            self._closed=True
            owners=[owner for owner in self._owners.values() if owner]
            for name in PROFILES: self._generations[name]+=1
            for owner in owners: owner.stop()
        results=[owner.close(timeout=max(0,deadline-time.monotonic())) for owner in owners]
        return all(results)
