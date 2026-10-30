from contextlib import contextmanager
import json


def test_managed_acceptance_records_failure_without_claiming_silence(tmp_path, monkeypatch):
    from tools import voice_route_acceptance as harness
    cleaned = []
    @contextmanager
    def graph(**kwargs):
        try:
            raise TimeoutError('private_graph_missing')
            yield
        finally:
            cleaned.append(True)
    monkeypatch.setattr(harness, 'private_graph', graph)
    output = tmp_path / 'report'
    assert harness.main(['--output', str(output), '--runs', '1', '--soak-seconds', '0']) == 1
    report = json.loads((output / 'report.json').read_text())
    assert report['status'] == 'failed' and report['failure_code'] == 'private_graph_missing'
    assert report['rows'] == [] and not report['vrchat_verified']
    assert cleaned == [True]
