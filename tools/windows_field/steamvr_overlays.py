"""A second OpenVR client: which VRCT overlays exist on the real runtime, and their pixels."""
import ctypes
import json
import os
from pathlib import Path
import sys

BASE = Path(os.environ.get('VOX_FIELD_ROOT') or Path(__file__).resolve().parents[2]) / 'build/model-test/steamvr'
os.environ['VR_CONFIG_PATH'] = str(BASE / 'config')
os.environ['VR_LOG_PATH'] = str(BASE / 'logs')
import numpy as np  # noqa: E402
import openvr  # noqa: E402
from PIL import Image  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
openvr.init(openvr.VRApplication_Background)
overlay = openvr.VROverlay()
result = {}
names = ['VRCT0', 'VRCT1', 'VRCT2', 'VRCT_toolbar', 'VRCT_tooltip', 'VRCT_resize_ghost', 'VRCT_pointer_small', 'VRCT_pointer_large']
for key in names:
    try:
        handle = overlay.findOverlay(key)
    except openvr.error_code.OverlayError as error:
        result[key] = 'missing'
        continue
    row = {'visible': bool(overlay.isOverlayVisible(handle))}
    try:
        width, height, _ = overlay.getOverlayImageData(handle, None, 0)[1:] if False else (0, 0, 0)
    except Exception:
        width = height = 0
    try:
        size = 4096 * 4096 * 4
        buffer = (ctypes.c_uint8 * size)()
        got = overlay.getOverlayImageData(handle, buffer, size)
        width, height = (got[0], got[1]) if isinstance(got, tuple) else (0, 0)
        row.update(width=width, height=height)
        if width and height:
            pixels = np.frombuffer(buffer, dtype=np.uint8, count=width * height * 4).reshape(height, width, 4)
            row.update(alpha_max=int(pixels[..., 3].max()), lit=int((pixels[..., 3] > 16).sum()))
            Image.fromarray(pixels.copy(), 'RGBA').save(out / f'{key}.png')
    except Exception as error:
        row['image_error'] = repr(error)[:140]
    result[key] = row
print('OVERLAYS ' + json.dumps(result), flush=True)
openvr.shutdown()
