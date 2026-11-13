# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
from distribution_policy import filter_toc
from windows_voice_resources import notice_toc, sidecar_version, voice_toc

_use_upx = os.environ.get("VRCT_PYINSTALLER_UPX") == "1"


a = Analysis(
    ['..\\src-python\\mainloop.py'],
    # A stand-in for PyAV keeps its GPL x264/x265 libraries out (see the stub).
    pathex=[str(Path(SPECPATH).resolve().parent / 'packaging' / 'pyinstaller-stubs')],
    binaries=[],
    datas=[
        ("./../LICENSE", "licenses/VRCT/"),
        ("./../NOTICE.md", "licenses/VRCT/"),
        ("./../src-tauri/nsis/licenses/nscurl", "licenses/nscurl/"),
        ('./../src-python/models/overlay/fonts', 'fonts/'),
        ('./../src-python/models/translation/translation_settings/prompt', 'translation_settings/prompt/'),
        ('./../src-python/models/translation/translation_settings/languages', 'translation_settings/languages/'),
        ('./../src-python/models/ocr/onnx/LICENSE.txt', 'ocr_onnx/'),
        ('./../src-python/models/ocr/onnx/LICENSE.en.txt', 'ocr_onnx/'),
        ('./../src-python/models/ocr/onnx/NOTICE.txt', 'ocr_onnx/'),
        ('./../.venv_cuda/Lib/site-packages/zeroconf', 'zeroconf/'),
        ('./../.venv_cuda/Lib/site-packages/openvr', 'openvr/'),
        ('./../.venv_cuda/Lib/site-packages/glfw', 'glfw/'),  # glfw3.dll (VR UI overlay texture) is loaded via ctypes, not found by analysis
        ('./../.venv_cuda/Lib/site-packages/faster_whisper', 'faster_whisper/'),
        ('./../.venv_cuda/Lib/site-packages/hf_xet', 'hf_xet/'),
        # RapidOCR reads these at start-up; nothing else in the package is data we ship
        # (its bundled weights are dropped by filter_toc and never used).
        ('./../.venv_cuda/Lib/site-packages/rapidocr/config.yaml', 'rapidocr/'),
        ('./../.venv_cuda/Lib/site-packages/rapidocr/default_models.yaml', 'rapidocr/'),
        ],
    # nvidia.cublas / nvidia.cudnn は ctranslate2 が GPU 実行時に
    # LoadLibrary で遅延ロードするDLLの提供元で、Python からは import
    # されないので依存解析に掛からない。ここで明示して
    # pyinstaller-hooks-contrib の hook-nvidia.* に _internal/nvidia/<lib>/bin/
    # へ収集させる (2026-09-18 に torch を落とすまでは、torch が同梱していた
    # 同じDLL群が torch 経由で収集されていた)。実行時のDLL検索パス登録は
    # src-python/utils.py の _registerBundledCudaLibraries が行う。
    hiddenimports=['faster_whisper.vad', 'rapidocr', 'rapidocr.inference_engine.onnxruntime', 'cv2', 'models.ocr', 'windows_capture',
                   'nvidia.cublas', 'nvidia.cudnn',
                   'soxr', 'pyaudiowpatch', 'models.transcription.capture_windows', 'models.audio_routing.windows_route',
                   'models.voice_conversion.router_worker', 'models.voice_conversion.rvc_process',
                   'models.voice_conversion.seed_process'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pandas', 'matplotlib', 'PyQt5'],
    # LGPL Python code stays as replaceable source files outside the PYZ archive.
    # Transformers lists the folder next to each package's __file__ to build its lazy imports.
    # Inside the PYZ archive that __file__ is a .pyc that is not on the disk, the listing fails,
    # and no tokenizer can be built (local translation never turns on). As source files it works.
    module_collection_mode={'zeroconf': 'py', 'bidi': 'py', 'transformers': 'py'},
    noarchive=False,
    optimize=0,
)
a.datas += voice_toc(ROOT) + notice_toc()
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
    version=sidecar_version(ROOT),
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
