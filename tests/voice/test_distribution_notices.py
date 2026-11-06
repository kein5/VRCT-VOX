"""Notice selection and locked component attribution without building packages."""
import ast
from pathlib import Path
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[2]
NSCURL_NOTICES = {
    "LICENSE.md", "LICENSE.brotli.md", "LICENSE.curl.md", "LICENSE.nghttp2.md",
    "LICENSE.openssl.md", "LICENSE.zlib.md", "LICENSE.zstd.md",
}


@pytest.mark.parametrize("spec_name", ["backend.spec", "backend_cuda.spec"])
def test_windows_payload_collects_retained_nscurl_notices(spec_name):
    spec = ROOT / "spec" / spec_name
    tree = ast.parse(spec.read_text(encoding="utf-8"))
    analysis = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Analysis")
    datas = ast.literal_eval(next(kw.value for kw in analysis.keywords if kw.arg == "datas"))
    sources = [source for source, target in datas if target.rstrip("/") == "licenses/nscurl"]
    assert len(sources) == 1
    directory = (spec.parent / sources[0]).resolve()
    assert directory == ROOT / "src-tauri/nsis/licenses/nscurl"
    assert {path.name for path in directory.iterdir()} == NSCURL_NOTICES
    assert all(path.stat().st_size for path in directory.iterdir())


def test_bootstrapper_embeds_nscurl_notices_before_any_download():
    source = (ROOT / "src-tauri/nsis/template.nsi").read_text(encoding="utf-8")
    init = source.split("Function .onInit\n", 1)[1].split("FunctionEnd", 1)[0]
    assert 'SetOutPath "$PLUGINSDIR\\licenses\\nscurl"' in init
    assert 'File "..\\..\\..\\..\\nsis\\licenses\\nscurl\\LICENSE*.md"' in init
    assert "InitPluginsDir" in init
    assert "NScurl::" not in init


def test_zeroconf_notice_matches_locked_version_and_source():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    component = next(package for package in lock["package"] if package["name"] == "zeroconf")
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    row = next(line for line in notice.splitlines() if line.startswith("| `zeroconf` "))
    assert f"| `zeroconf` {component['version']} (Python) |" in row
    assert f"]({component['sdist']['url']})" in row
    for name in ("backend.spec", "backend_cuda.spec", "backend_linux.spec"):
        tree = ast.parse((ROOT / "spec" / name).read_text(encoding="utf-8"))
        modes = [ast.literal_eval(node.value) for node in ast.walk(tree)
                 if isinstance(node, ast.keyword) and node.arg == "module_collection_mode"]
        assert len(modes) == 1 and modes[0]["zeroconf"] == "py"
