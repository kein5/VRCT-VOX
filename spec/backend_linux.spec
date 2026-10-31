# -*- mode: python ; coding: utf-8 -*-
"""Linux onedir; resources are explicitly selected, never copy the OCR directory or OCR weights."""
import os
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(root / 'tools'))
from distribution_policy import filter_toc

resources = Path(os.environ['VRCT_LINUX_RESOURCES'])
datas = [(str(resources), '.')]
for source, destination in (
    ('LICENSE', 'licenses/VRCT'), ('NOTICE.md', 'licenses/VRCT'),
    ('src-python/models/overlay/fonts', 'fonts'),
    ('src-python/models/translation/translation_settings/prompt', 'translation_settings/prompt'),
    ('src-python/models/translation/translation_settings/languages', 'translation_settings/languages'),
    ('src-python/models/ocr/onnx/LICENSE.txt', 'ocr_onnx'),
    ('src-python/models/ocr/onnx/LICENSE.en.txt', 'ocr_onnx'),
    ('src-python/models/ocr/onnx/NOTICE.txt', 'ocr_onnx'),
):
    datas.append((str(root / source), destination))

# These packages load data/native libraries dynamically, outside static imports.
for package in ('faster_whisper', 'openvr', 'glfw', 'sudachipy', 'sudachidict_core', 'sudachidict_full'):
    datas += collect_data_files(package)
# RapidOCR reads its YAML config at start-up. Only that is collected: its bundled
# weights are never shipped (filter_toc) and never loaded (explicit model paths).
datas += collect_data_files('rapidocr', includes=['*.yaml'])
binaries = collect_dynamic_libs('openvr') + collect_dynamic_libs('glfw')
for package in ('ctranslate2', 'transformers', 'faster-whisper', 'huggingface-hub',
                'tokenizers', 'safetensors', 'regex', 'requests', 'numpy',
                'packaging', 'filelock', 'tqdm', 'pyyaml'):
    datas += copy_metadata(package)

# The PyAV stand-in comes first so its GPL x264/x265 libraries stay out (see the stub).
a = Analysis([str(root / 'src-python/mainloop.py')], pathex=[str(root / 'packaging/pyinstaller-stubs'), str(root / 'src-python')],
    binaries=binaries, datas=datas,
    hiddenimports=['models.voice_conversion.router_worker',
                   'faster_whisper.vad', 'cv2', 'models.ocr',
                   'rapidocr', 'rapidocr.inference_engine.onnxruntime'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['pandas', 'matplotlib', 'PyQt5', 'torch', 'tensorflow',
              'windows_capture', 'pytest', 'ruff'], noarchive=False, optimize=0,
    # LGPL Python code stays as replaceable source files outside the PYZ archive.
    module_collection_mode={'zeroconf': 'py', 'bidi': 'py'})
a.datas = filter_toc(a.datas)
a.binaries = filter_toc(a.binaries)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='vrct-vox-sidecar',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='backend')
