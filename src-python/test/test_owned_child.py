"""Child ownership and pipe I/O that stand in for pidfd, pass_fds and select on Windows."""
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from models.owned_child import PipeWriter, launch_owned, wait_readable

windows = pytest.mark.skipif(sys.platform != 'win32', reason='Windows job objects')


def alive(pid):
    listing = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
    return str(pid) in listing


def wait_until(check, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(.02)
    return check()


def test_pipe_read_wait_times_out_then_sees_data_and_eof():
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, 'rb', buffering=0) as stream:
        assert wait_readable(stream, .03) is False
        os.write(write_fd, b'x')
        assert wait_readable(stream, 1) is True
        assert os.read(stream.fileno(), 1) == b'x'
        os.close(write_fd)
        assert wait_readable(stream, 1) is True
        assert os.read(stream.fileno(), 1) == b''


@windows
def test_a_write_the_reader_never_takes_does_not_block_the_caller():
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(write_fd, 'wb', buffering=0)
    writer = PipeWriter(stream)
    frame = b'x' * 200_000  # Far beyond the pipe's buffer: the writer thread stays inside write().
    started = time.monotonic()
    assert writer.write(frame) == len(frame)
    with pytest.raises(BlockingIOError):
        writer.write(b'y')
    assert writer.wait(.02) is False
    assert writer.flush(.02) is False
    assert time.monotonic() - started < 1
    received = 0
    while received < len(frame):
        received += len(os.read(read_fd, 65536))
    assert writer.flush(2) is True
    assert writer.write(b'z') == 1
    assert os.read(read_fd, 1) == b'z'
    writer.close()
    stream.close()
    os.close(read_fd)


@windows
def test_a_closed_reader_surfaces_as_a_broken_pipe():
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(write_fd, 'wb', buffering=0)
    writer = PipeWriter(stream)
    os.close(read_fd)
    writer.write(b'x')
    assert wait_until(lambda: writer.wait(0))
    with pytest.raises(BrokenPipeError):
        writer.write(b'y')
    stream.close()


@windows
def test_child_output_stays_binary_and_exit_status_is_kept():
    child = launch_owned([sys.executable, '-c', 'import os,sys; os.write(1, b"a\\nb"); sys.exit(7)'],
                         stdout=subprocess.PIPE)
    assert child.stdout.read() == b'a\nb'
    assert child.wait(10) == 7


@windows
def test_child_dies_with_its_owner_even_when_the_owner_is_killed(tmp_path):
    """A kill gives the owner no chance to clean up: only the job can end the child."""
    report = tmp_path / 'pid'
    source = Path(__file__).resolve().parents[1]
    script = tmp_path / 'owner.py'
    script.write_text(f'''
import subprocess, sys, time
sys.path.insert(0, {str(source)!r})
from models.owned_child import launch_owned
child = launch_owned([sys.executable, '-c', 'import time; time.sleep(60)'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
open({str(report)!r}, 'w').write(str(child.pid))
time.sleep(60)
''', encoding='utf-8')
    owner = subprocess.Popen([sys.executable, str(script)])
    try:
        assert wait_until(lambda: report.exists() and report.read_text(), 30)
        pid = int(report.read_text())
        assert alive(pid)
        owner.kill()
        owner.wait(10)
        assert wait_until(lambda: not alive(pid))
    finally:
        owner.kill()
