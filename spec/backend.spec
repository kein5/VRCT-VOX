# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH).resolve().parent / "tools"))
from distribution_policy import filter_toc

# UPX compression roughly doubles the PyInstaller collect step and adds
# a few seconds to sidecar startup. Default to disabled so ordinary
# rebuilds are fast; release scripts can opt in by setting
# VRCT_PYINSTALLER_UPX=1.
_use_upx = os.environ.get("VRCT_PYINSTALLER_UPX") == "1"


a = Analysis(
    ['..\\src-python\\mainloop.py'],
    # A stand-in for PyAV keeps its GPL x264/x265 libraries out (see the stub).
    pathex=[str(Path(SPECPATH).resolve().parent / 'packaging' / 'pyinstaller-stubs')],
    binaries=[],
    datas=[
        ("./../LICENSE", "licenses/VRCT/"),
        ("./../NOTICE.md", "licenses/VRCT/"),
        ('./../src-python/models/overlay/fonts', 'fonts/'),
        ('./../src-python/models/translation/translation_settings/prompt', 'translation_settings/prompt/'),
        ('./../src-python/models/translation/translation_settings/languages', 'translation_settings/languages/'),
        ('./../src-python/models/ocr/onnx/LICENSE.txt', 'ocr_onnx/'),
        ('./../src-python/models/ocr/onnx/LICENSE.en.txt', 'ocr_onnx/'),
        ('./../src-python/models/ocr/onnx/NOTICE.txt', 'ocr_onnx/'),
        ('./../.venv/Lib/site-packages/zeroconf', 'zeroconf/'),
        ('./../.venv/Lib/site-packages/openvr', 'openvr/'),
        ('./../.venv/Lib/site-packages/glfw', 'glfw/'),  # glfw3.dll (VR UI overlay texture) is loaded via ctypes, not found by analysis
        ('./../.venv/Lib/site-packages/faster_whisper', 'faster_whisper/'),
        ('./../.venv/Lib/site-packages/hf_xet', 'hf_xet/'),
        # RapidOCR reads these at start-up; nothing else in the package is data we ship
        # (its bundled weights are dropped by filter_toc and never used).
        ('./../.venv/Lib/site-packages/rapidocr/config.yaml', 'rapidocr/'),
        ('./../.venv/Lib/site-packages/rapidocr/default_models.yaml', 'rapidocr/'),
        ],
    hiddenimports=['faster_whisper.vad', 'models.transcription.audio_pipeline', 'rapidocr', 'rapidocr.inference_engine.onnxruntime', 'cv2', 'models.ocr', 'windows_capture'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pandas', 'matplotlib', 'PyQt5'],
    # LGPL Python code stays as replaceable source files outside the PYZ archive.
    module_collection_mode={'zeroconf': 'py', 'bidi': 'py'},
    noarchive=False,
    optimize=0,
)
# Exclude all OCR weights (including RapidOCR hooks), retain attribution.
# Inspect both source and destination names in the expanded TOC.
a.datas = filter_toc(a.datas)
a.binaries = filter_toc(a.binaries)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='vrct-vox-sidecar-x86_64-pc-windows-msvc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=_use_upx,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=_use_upx,
    upx_exclude=[],
    name='.',
)
