"""偽の SteamVR を差し込んだバックエンドで、コマンドを実行する (VR の機器なしで VR UI を試す)。

    python tools/run_with_fake_vr.py --out build/fake-vr -- npx tauri dev

コマンドから起動されたバックエンド (src-python/mainloop.py) だけが、本物の SteamVR の代わりに
src-python/test/fake_openvr.py につながる。ヘッドセットに出るはずの画像とオーバーレイの状態は
--out に書き出され、control.json でコントローラを動かせる (tools/fake_vr_site/fake_vr_recorder.py)。
製品のコードと設定は変えない。コマンドを省くと、自分で設定するための環境変数を表示する。
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "tools" / "fake_vr_site"


def environment(out: Path, base=None) -> dict:
    env = dict(os.environ if base is None else base)
    paths = [str(SITE)] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["VOX_FAKE_VR_OUT"] = str(out)
    return env


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "fake-vr", help="画像と状態の出力先")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- の後ろに実行するコマンド")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    env = environment(out)
    if not command:
        print(f"PYTHONPATH={env['PYTHONPATH']}")
        print(f"VOX_FAKE_VR_OUT={out}")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    executable = shutil.which(command[0]) or command[0]  # Windows の npm.cmd / npx.cmd も見つける
    print(f"fake-vr: {out} に書き出します", file=sys.stderr)
    return subprocess.call([executable, *command[1:]], env=env, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
