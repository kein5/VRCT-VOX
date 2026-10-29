"""The control pipe cannot carry unbounded or untrusted health state."""
import time
import sys

import pytest

from models.voice_conversion.router_protocol import BASE_STATE, validate_health, encode

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux isolated transport')


def message(**changes):
    return dict(kind='health', sent_ns=time.monotonic_ns(), **(BASE_STATE | changes))


def test_health_accepts_only_fresh_complete_typed_state():
    frame = message(active=True, requested=True, state='converted', conversion_verified=True,
                    converted_blocks=12)
    assert validate_health(frame)['converted_blocks'] == 12


@pytest.mark.parametrize('change', [dict(active=1), dict(converted_blocks=True),
    dict(converted_blocks=-1), dict(state='unknown'), dict(error='/private/file'),
    dict(error='vc_'+'x'*100)])
def test_bad_health_rejected(change):
    with pytest.raises(ValueError):
        validate_health(message(**change))


def test_stale_future_extra_and_missing_fields_are_rejected():
    base = message()
    for change in (dict(sent_ns=1), dict(sent_ns=time.monotonic_ns()+2_000_000_000),
                   dict(extra=True), dict(kind='start')):
        with pytest.raises(ValueError):
            validate_health(base | change)
    del base['state']
    with pytest.raises(ValueError):
        validate_health(base)


def test_control_encoding_is_bounded_and_has_one_frame():
    assert encode({'name': 'line\nbreak'}).count(b'\n') == 1
    with pytest.raises(ValueError):
        encode({'padding': 'a'*32768})


@pytest.mark.parametrize('wire', [b'x'*32768, b'{bad}\n', b''])
def test_reader_rejects_oversize_malformed_and_eof(wire, tmp_path):
    from models.voice_conversion.router_protocol import Reader
    path = tmp_path/'wire'
    path.write_bytes(wire)
    with path.open('rb') as stream, pytest.raises((ValueError, EOFError)):
        Reader(stream).read(timeout=.1)


def test_reader_timeout_and_cancellation():
    import os
    from models.voice_conversion.router_protocol import Reader
    read, write = os.pipe()
    try:
        with os.fdopen(read, 'rb') as stream:
            reader = Reader(stream)
            with pytest.raises(TimeoutError):
                reader.read(timeout=.02)
            def cancelled():
                raise RuntimeError('cancelled')
            with pytest.raises(RuntimeError, match='cancelled'):
                reader.read(timeout=10, check=cancelled)
    finally:
        os.close(write)


def test_frozen_worker_entry_does_not_import_controller(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    script = '''
import sys,runpy
class Deny:
 def find_spec(self, fullname, *args):
  if fullname == 'controller': raise AssertionError('heavy Controller import')
sys.meta_path.insert(0,Deny())
sys.path.insert(0,'src-python')
sys.argv=['src-python/mainloop.py','--voice-router-worker']
runpy.run_path(sys.argv[0],run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-c', script], input=b'{bad}\n',
                            capture_output=True, timeout=3, cwd=Path(__file__).resolve().parents[2])
    assert result.returncode == 1 and not result.stderr
