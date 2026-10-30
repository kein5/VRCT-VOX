import pytest
from test_managed_route import Gate, Store


def test_cli_mute_reports_native_confirmation_and_persists():
    from tools.voice_route import control
    gate, store = Gate(), Store()
    result = control('mute', gate=gate, store=store)
    assert result['observed_muted'] and store.value


def test_cli_resume_storage_failure_recloses_gate():
    from tools.voice_route import control
    gate, store = Gate(), Store(True)
    gate.muted = True
    store.fail = True
    with pytest.raises(OSError):
        control('resume', gate=gate, store=store)
    assert gate.muted


def test_cli_mute_attempts_native_even_if_disk_fails():
    from tools.voice_route import control
    gate, store = Gate(), Store()
    store.fail = True
    with pytest.raises(OSError):
        control('mute', gate=gate, store=store)
    assert gate.muted
