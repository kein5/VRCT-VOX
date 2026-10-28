# SPDX-License-Identifier: GPL-3.0-only
import importlib
import io

import pytest


def test_worker_spawn_failure_releases_output_and_bridge(tmp_path, monkeypatch):
    module = importlib.import_module('integrations.seed_vc.acceptance')
    closed = []

    class Bridge:
        def configure(self, source):
            pass

        def close(self):
            closed.append('bridge')
            return True

    class Output:
        def __init__(self, *args):
            pass

        def close(self, **kwargs):
            closed.append('output')

    def fail(*args, **kwargs):
        raise FileNotFoundError('no worker runtime')

    monkeypatch.setattr(module, 'SourceBridge', Bridge)
    monkeypatch.setattr(module, 'PipeWireOutput', Output)
    monkeypatch.setattr(module, 'graph_snapshot', lambda: [])
    monkeypatch.setattr(module, 'select_source', lambda *args: None)
    monkeypatch.setattr(module.subprocess, 'Popen', fail)
    with pytest.raises(FileNotFoundError):
        module.WorkerRoute(tmp_path, io.BytesIO())
    assert set(closed) == {'output', 'bridge'}
