"""Attempt every owned-resource cleanup before finalizing an acceptance result."""


def finalize_acceptance(report, steps, persist, *, error=None):
    errors = []
    for name, action in steps:
        try:
            report.setdefault('cleanup', {})[name] = action()
        except BaseException as exc:
            errors.append({'step': name, 'error': repr(exc)})
    if errors:
        report['status'] = 'failed'
        report['cleanup_errors'] = errors
    elif report['status'] in ('verified', 'smoke_verified'):
        report['status'] = 'passed' if report['status'] == 'verified' else 'smoke_passed'
        for case in report.get('cases', []):
            if case['status'] == 'observed_pending_final_validation':
                case['status'] = 'passed'
    try:
        persist()
    except BaseException as exc:
        errors.append({'step': 'persist', 'error': repr(exc)})
        report.update(status='failed', cleanup_errors=errors)
    if errors:
        message = 'acceptance_cleanup_failed: ' + repr(errors)
        if error is not None:
            error.add_note(message)
        else:
            raise RuntimeError(message)
