import pytest

from tools.acceptance_lifecycle import finalize_acceptance


def test_failed_capture_cleanup_cannot_skip_mute_watch_or_ime_restore():
    calls = []
    def broken():
        calls.append('capture')
        raise OSError('capture cleanup failed')
    report = {'status':'verified', 'cases':[{'status':'observed_pending_final_validation'}]}
    with pytest.raises(RuntimeError, match='acceptance_cleanup_failed'):
        finalize_acceptance(report, [('capture',broken),
            ('mute',lambda:calls.append('mute')), ('watch',lambda:calls.append('watch')),
            ('ime',lambda:calls.append('ime'))], lambda:calls.append('save'))
    assert calls == ['capture','mute','watch','ime','save']
    assert report['status']=='failed'
    assert report['cases'][0]['status']!='passed'


def test_primary_test_error_is_preserved_and_cleanup_error_added():
    original = ValueError('original failure')
    def broken(): raise OSError('mute failed')
    report={'status':'failed'}
    finalize_acceptance(report,[('mute',broken)],lambda:None,error=original)
    assert report['cleanup_errors'][0]['step']=='mute'
    assert 'mute failed' in original.__notes__[0]


def test_pass_is_persisted_only_after_all_cleanup_succeeds():
    report={'status':'verified','cases':[{'status':'observed_pending_final_validation'}]}
    def cleanup():
        assert report['status']=='verified'
        return {'muted':True}
    saved=[]
    finalize_acceptance(report,[('mute',cleanup)],lambda:saved.append(report['status']))
    assert saved==['passed']
    assert report['cleanup']['mute']=={'muted':True}
    assert report['cases'][0]['status']=='passed'


def test_save_failure_cannot_return_success():
    report={'status':'verified','cases':[]}
    def broken():raise OSError('disk full')
    with pytest.raises(RuntimeError,match='acceptance_cleanup_failed'):
        finalize_acceptance(report,[],broken)
    assert report['status']=='failed'
