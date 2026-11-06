"""アプリに差し込んだ偽の SteamVR の様子を、ファイルに書き出し・ファイルから操作する。

書き出すもの (出力先は VOX_FAKE_VR_OUT):
- state.json   オーバーレイ (表示・位置・大きさ・画像) とデバイスの状態。1秒ごとに書き換える
- <key>.png    各オーバーレイに今出ている画像。テクスチャのものは、表示範囲 (bounds) で切り出す
- texture-<n>.png  VR画面のテクスチャ全体

操作 (control.json を書き換えると、次の確認で1回だけ反映する):
    {"aim": {"device": "right", "overlay": "VRCT0", "at": [0.0, 0.0], "distance": 0.4},
     "press": {"right": ["trigger"]}, "release": {"right": ["trigger"]},
     "steamvr_running": true, "quit": false}
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import openvr

_DEVICES = {"hmd": 0, "left": 1, "right": 2}
_BUTTONS = {
    "trigger": openvr.k_EButton_SteamVR_Trigger,
    "grip": openvr.k_EButton_Grip,
    "menu": openvr.k_EButton_ApplicationMenu,
    "a": openvr.k_EButton_A,
}


def _log(message: str) -> None:
    print(f"fake-vr: {message}", file=sys.stderr, flush=True)


def _laser_pitch() -> float:
    """アプリがレーザーを上げる角度。aim でその分だけコントローラを下げ、レーザーを狙った点に当てる。"""
    overlay = sys.modules.get("models.overlay.overlay")
    return float(getattr(overlay, "_LASER_PITCH_UP_DEG", 0.0))


class Recorder:
    def __init__(self, vr, out: Path, interval: float = 1.0) -> None:
        self.vr = vr
        self.out = out
        self.interval = interval
        self.lock = threading.Lock()
        self.textures: Dict[int, Tuple[int, int, bytes]] = {}  # OpenGL の番号 -> (幅, 高さ, RGBA)
        self.texture_read_at: Dict[int, float] = {}
        self.written: Dict[str, Any] = {}
        self.control_mtime: Optional[float] = None
        self.stop = threading.Event()
        self.out.mkdir(parents=True, exist_ok=True)

    # --- オーバーレイのスレッドから (OpenGL の環境が今のもの) ---

    def texture_size(self, handle: int) -> Optional[Tuple[int, int]]:
        size = self.vr.texture_sizes.get(handle)
        if size is not None:
            return size
        try:
            from OpenGL import GL

            previous = GL.glGetIntegerv(GL.GL_TEXTURE_BINDING_2D)
            GL.glBindTexture(GL.GL_TEXTURE_2D, handle)
            size = (int(GL.glGetTexLevelParameteriv(GL.GL_TEXTURE_2D, 0, GL.GL_TEXTURE_WIDTH)),
                    int(GL.glGetTexLevelParameteriv(GL.GL_TEXTURE_2D, 0, GL.GL_TEXTURE_HEIGHT)))
            GL.glBindTexture(GL.GL_TEXTURE_2D, int(previous))
        except Exception as e:  # noqa: BLE001  撮れなくてもアプリは止めない
            _log(f"texture size of {handle} unavailable: {e!r}")
            return None
        if size[0] > 0 and size[1] > 0:
            self.vr.texture_sizes[handle] = size
            return size
        return None

    def on_texture(self, state, texture) -> None:
        handle = int(texture.handle or 0)
        if texture.eType != openvr.TextureType_OpenGL or not handle:
            return
        now = time.monotonic()
        if now - self.texture_read_at.get(handle, 0.0) < self.interval:
            return
        self.texture_read_at[handle] = now
        size = self.texture_size(handle)
        if size is None:
            return
        try:
            from OpenGL import GL

            previous = GL.glGetIntegerv(GL.GL_TEXTURE_BINDING_2D)
            GL.glBindTexture(GL.GL_TEXTURE_2D, handle)
            data = GL.glGetTexImage(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
            GL.glBindTexture(GL.GL_TEXTURE_2D, int(previous))
            while GL.glGetError() != GL.GL_NO_ERROR:  # 自分の呼び出しのエラーをアプリに残さない
                pass
        except Exception as e:  # noqa: BLE001
            _log(f"reading texture {handle} failed: {e!r}")
            return
        data = data.tobytes() if hasattr(data, "tobytes") else bytes(data)
        with self.lock:
            self.textures[handle] = (size[0], size[1], data)

    # --- 書き出しのスレッド ---

    def start(self) -> None:
        threading.Thread(target=self.run, name="fake-vr-recorder", daemon=True).start()

    def run(self) -> None:
        while not self.stop.wait(self.interval):
            try:
                self.apply_control()
                self.write()
            except Exception as e:  # noqa: BLE001
                _log(f"recorder: {e!r}")

    def apply_control(self) -> None:
        path = self.out / "control.json"
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime == self.control_mtime:
            return
        self.control_mtime = mtime
        control = json.loads(path.read_text(encoding="utf-8") or "{}")
        vr = self.vr
        with vr.lock:
            if "steamvr_running" in control:
                vr.steamvr_running = bool(control["steamvr_running"])
            if control.get("quit"):
                vr.quit()
            aim = control.get("aim")
            if aim:
                state = vr.overlay_by_key(aim["overlay"])
                if state is None:
                    _log(f"control: no overlay {aim['overlay']!r}")
                else:
                    vr.aim(_DEVICES[aim.get("device", "right")], state, at=tuple(aim.get("at", (0.0, 0.0))),
                           distance=float(aim.get("distance", 0.4)),
                           laser_pitch_deg=float(aim.get("laser_pitch_deg", _laser_pitch())))
            for action in ("press", "release"):
                for device, buttons in (control.get(action) or {}).items():
                    getattr(vr.devices[_DEVICES[device]], action)(*(_BUTTONS[b] for b in buttons))
        _log(f"control applied: {sorted(control)}")

    def write(self) -> None:
        vr = self.vr
        with self.lock:
            textures = dict(self.textures)
        overlays = []
        with vr.lock:
            states = list(vr.overlays.values())
            for state in states:
                pose = vr.world_pose(state)
                overlays.append({
                    "key": state.key, "name": state.name, "visible": state.visible,
                    "alpha": round(state.alpha, 3), "width_m": round(state.width_m, 4), "sort_order": state.sort_order,
                    "transform": None if state.transform is None else {
                        "kind": state.transform[0], "target": state.transform[1],
                        "matrix": [[round(v, 4) for v in row] for row in state.transform[2][:3]]},
                    "world_position": None if pose is None else [round(v, 4) for v in pose[:3, 3]],
                    "raw_size": None if state.raw is None else list(state.raw[1:3]),
                    "texture": None if state.texture is None else state.texture[0],
                    "bounds": [round(v, 4) for v in state.bounds],
                    "raw_updates": state.raw_updates, "texture_updates": state.texture_updates,
                    "png": self.write_image(state, textures),
                })
            summary = {
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "connected": vr.connected,
                "steamvr_running": vr.steamvr_running, "init_calls": vr.init_calls,
                "shutdown_calls": vr.shutdown_calls, "misuse": list(vr.misuse),
                "leaked": [s.key for s in vr.leaked],
                "devices": {name: {"buttons": vr.devices[i].buttons,
                                   "position": [round(v, 3) for v in vr.devices[i].pose[:3, 3]]}
                            for name, i in _DEVICES.items()},
                "overlays": overlays,
            }
        for handle, (width, height, data) in textures.items():
            key = f"texture-{handle}"
            if self.written.get(key) is not data:
                self.save_png(f"{key}.png", width, height, data)
                self.written[key] = data
        temporary = self.out / "state.json.tmp"
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, self.out / "state.json")

    def write_image(self, state, textures) -> Optional[str]:
        name = f"{state.key}.png"
        if state.raw is not None:
            stamp = ("raw", state.raw_updates)
            if self.written.get(name) != stamp:
                state.image().save(self.out / name)
                self.written[name] = stamp
            return name
        if state.texture is None or state.texture[0] not in textures:
            return None
        width, height, data = textures[state.texture[0]]
        stamp = ("texture", id(data), state.bounds)
        if self.written.get(name) != stamp:
            from PIL import Image

            u0, u1, v0, v1 = state.bounds
            # 画像の上から y 行目は v = 1 - y/H (実機で確かめた向き。overlay.py の regionBounds)
            box = (round(min(u0, u1) * width), round((1 - max(v0, v1)) * height),
                   round(max(u0, u1) * width), round((1 - min(v0, v1)) * height))
            Image.frombytes("RGBA", (width, height), data).crop(box).save(self.out / name)
            self.written[name] = stamp
        return name

    def save_png(self, name: str, width: int, height: int, data: bytes) -> None:
        from PIL import Image

        Image.frombytes("RGBA", (width, height), data).save(self.out / name)
