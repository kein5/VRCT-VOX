"""Child lifetime and pipe I/O where Windows lacks pidfd, pass_fds and select on pipes.

A launched child sits in its own kill-on-close job: when the owning process
dies for any reason the kernel closes the handle and ends the child, the same
promise the Linux helper's pidfd watch gives. Pipes get a nonblocking write
through a writer thread, because Windows pipes have no O_NONBLOCK before
Python 3.12 and a blocking write must never stall an audio or control loop.
"""
import os
from queue import Empty, Full, Queue
import select
import subprocess
from threading import Condition, Thread
import time

_POLL = .002


class _Job:
    """A kill-on-close job object holding one child."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self._kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self._kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        self._kernel.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
        self._kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self._kernel.OpenProcess.restype = wintypes.HANDLE
        self._kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self._kernel.CloseHandle.argtypes = (wintypes.HANDLE,)

        class Basic(ctypes.Structure):
            _fields_ = [('per_process_time', ctypes.c_int64), ('per_job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                        ('max_working_set', ctypes.c_size_t), ('process_limit', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

        self._handle = self._kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel.SetInformationJobObject(self._handle, 9, ctypes.byref(limits),
                                                    ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def hold(self, pid):
        """Assign a suspended process and let it run; it cannot escape before it starts."""
        ctypes = self._ctypes
        # PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_SUSPEND_RESUME
        process = self._kernel.OpenProcess(0x0001 | 0x0100 | 0x0800, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self._kernel.AssignProcessToJobObject(self._handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
            ntdll = ctypes.WinDLL('ntdll')
            ntdll.NtResumeProcess.argtypes = (ctypes.c_void_p,)
            if ntdll.NtResumeProcess(process) != 0:
                raise OSError('resume_failed')
        finally:
            self._kernel.CloseHandle(process)

    def close(self):
        handle, self._handle = self._handle, None
        if handle:
            self._kernel.CloseHandle(handle)

    def __del__(self):
        self.close()


def launch_owned(args, *, stdin=None, stdout=None, stderr=None, env=None, cwd=None, realtime=False):
    """Windows only. The returned Popen keeps its job for as long as it lives.

    realtime lifts the child above normal priority: an audio block has a fixed
    deadline, and a busy game otherwise takes the CPU it needs to feed the GPU.
    """
    job = _Job()
    try:
        # A console-less sidecar would otherwise open a window for each child.
        child = subprocess.Popen(
            args, stdin=stdin, stdout=stdout, stderr=stderr, env=env, cwd=cwd, bufsize=0,
            creationflags=(subprocess.CREATE_NO_WINDOW | 0x00000004  # CREATE_SUSPENDED
                           | (subprocess.ABOVE_NORMAL_PRIORITY_CLASS if realtime else 0)))
    except BaseException:
        job.close()
        raise
    try:
        job.hold(child.pid)
    except BaseException:
        child.kill()
        child.wait()
        job.close()
        raise
    child.owner_job = job
    return child


def wait_readable(stream, timeout):
    """True when a read would not block, EOF included. select() rejects Windows pipes."""
    if os.name != 'nt':
        return bool(select.select([stream], [], [], timeout)[0])
    import _winapi
    import msvcrt
    handle = msvcrt.get_osfhandle(stream.fileno())
    deadline = time.perf_counter() + timeout
    while True:
        try:
            if _winapi.PeekNamedPipe(handle, 0)[0]:
                return True
        except OSError:
            return True  # Writer gone: the read reports EOF.
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return False
        time.sleep(min(_POLL, remaining))


class PipeWriter:
    """Nonblocking writes to an unbuffered pipe; a full pipe raises BlockingIOError."""
    def __init__(self, stream):
        self.stream = stream
        self._fd = stream.fileno()
        self._thread = None
        if os.name != 'nt':
            os.set_blocking(self._fd, False)
            return
        self._queue = Queue(maxsize=1)
        self._ready = Condition()
        self._writing = False
        self._failed = False
        self._thread = Thread(target=self._pump, name='vrct-pipe-writer', daemon=True)
        self._thread.start()

    def _pump(self):
        while True:
            data = self._queue.get()
            if data is None:
                return
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(self._fd, view):]
            except OSError:
                with self._ready:
                    self._failed = True
                    self._writing = False
                    self._ready.notify_all()
                return
            with self._ready:
                self._writing = False
                self._ready.notify_all()

    def _idle(self):
        return not self._writing and self._queue.empty()

    def wait(self, timeout):
        """True when write() can take data now."""
        if self._thread is None:
            return bool(select.select([], [self.stream], [], timeout)[1])
        with self._ready:
            return self._ready.wait_for(lambda: self._failed or self._idle(), timeout)

    def write(self, data):
        """Bytes taken. Windows takes a whole frame or none, like an atomic pipe write."""
        if self._thread is None:
            return os.write(self._fd, data)
        with self._ready:
            if self._failed:
                raise BrokenPipeError('pipe_closed')
            if self._writing:
                raise BlockingIOError('pipe_full')
            try:
                self._queue.put_nowait(bytes(data))
            except Full:
                raise BlockingIOError('pipe_full') from None
            self._writing = True
        return len(data)

    def flush(self, timeout):
        """Wait for queued data; False means the reader never took it."""
        if self._thread is None:
            return True
        with self._ready:
            return self._ready.wait_for(lambda: self._failed or self._idle(), timeout)

    def close(self):
        """Stop the thread. It is left alone if it is still inside a write."""
        if self._thread is None:
            return
        try:
            self._queue.put_nowait(None)
        except Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(None)
            except (Empty, Full):
                pass
