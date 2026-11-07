"""バックエンド (src-python/mainloop.py) の起動時に、偽の SteamVR を差し込む。

tools/run_with_fake_vr.py がこのディレクトリを PYTHONPATH に入れ、出力先を VOX_FAKE_VR_OUT に
入れて起動する。Python は起動時に sitecustomize を読み込むので、製品のコードを変えずに差し込める。
mainloop.py 以外 (npm から呼ばれる別の Python など) では何もしない。
"""

import os
import sys


def _activate() -> None:
    out = os.environ.get("VOX_FAKE_VR_OUT")
    script = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not out or script != "mainloop.py":
        return
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    # models.process_check を mainloop より先に読み込んで差し替えるため、src-python を先に足す
    sys.path.insert(0, str(root / "src-python"))
    spec = importlib.util.spec_from_file_location("fake_openvr", root / "src-python/test/fake_openvr.py")
    fake_openvr = importlib.util.module_from_spec(spec)
    sys.modules["fake_openvr"] = fake_openvr
    spec.loader.exec_module(fake_openvr)
    from fake_vr_recorder import Recorder

    vr = fake_openvr.FakeOpenVR()
    recorder = Recorder(vr, Path(out))
    vr.on_texture = recorder.on_texture
    vr.texture_size_of = recorder.texture_size
    vr.install()
    recorder.start()
    print(f"fake-vr: SteamVR の代わりに偽の OpenVR を使います。出力先: {out}", file=sys.stderr, flush=True)


try:
    _activate()
except Exception:  # noqa: BLE001  差し込みに失敗しても、アプリの起動は止めない
    import traceback

    traceback.print_exc()
