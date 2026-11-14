"""The links the download screens show can be opened (second security audit SEC-02).

The main window may open only the URLs listed in src-tauri/capabilities/vrct_capability.json.
The model and runtime catalogs come from Python, so their source and license links are checked
here against the same list. fnmatchcase matches like the glob crate the opener plugin uses with
its default options (`*` also crosses `/`); src-tauri/src/opener_scope_tests.rs checks the list
with the glob crate itself.
"""
from fnmatch import fnmatchcase
import json
from pathlib import Path

import pytest

from models.model_downloads.manager import Downloads
from models.voice_conversion import runtime_setup as rs

ROOT = Path(__file__).resolve().parents[2]


def scope():
    capability = json.loads((ROOT / 'src-tauri/capabilities/vrct_capability.json').read_text(encoding='utf-8'))
    entry = next(item for item in capability['permissions']
                 if isinstance(item, dict) and item['identifier'] == 'opener:allow-open-url')
    return [item['url'] for item in entry['allow']], [item['url'] for item in entry.get('deny', [])]


def opens(url):
    allow, deny = scope()
    return not any(fnmatchcase(url, pattern) for pattern in deny) and any(fnmatchcase(url, pattern) for pattern in allow)


def test_every_model_source_and_license_link_can_be_opened(tmp_path):
    links = set()
    for model in Downloads(tmp_path).catalog()['models']:
        links.add(model['source'])
        links.update(model['sources'])
        links.update(model['licenses'])
    assert len(links) > 10
    assert [url for url in sorted(links) if not opens(url)] == []


@pytest.mark.parametrize('platform', ['win32', 'linux'])
def test_every_voice_changer_runtime_license_link_can_be_opened(monkeypatch, platform):
    monkeypatch.setattr(rs, 'target', lambda: platform)
    links = {url for runtime in rs.runtimes() for url in runtime.licenses}
    assert len(links) > 5
    assert [url for url in sorted(links) if not opens(url)] == []


def test_a_link_to_another_site_is_not_opened():
    assert not opens('https://example.com/')
    assert not opens('https://github.com/someone/else')
