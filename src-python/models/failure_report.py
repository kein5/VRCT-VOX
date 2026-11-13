"""Tells the usage events that a voice feature failed, by its fixed code.

The list of codes that may be reported is errors.REPORTED_FAILURES. This wrapper keeps the
audio and server code free of that dependency: a failure to report is never a failure of
the feature.
"""


def report_failure(area, code):
    try:
        from errors import report_failure as report
        report(area, code)
    except Exception:
        pass
