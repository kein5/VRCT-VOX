"""Files the Windows sidecar ships for speech.cpp and the external RVC worker.

The fixed speech.cpp bundle comes from speechcpp_bundle.py. External inference
interpreters cannot read the frozen sidecar's PYZ, so the RVC adapter and its small,
dependency-free contract modules ship as ordinary files.
"""
from pathlib import Path

CONTRACT = ('__init__.py', 'owned_child.py', 'voice_conversion/__init__.py',
            'voice_conversion/protocol.py', 'voice_conversion/settings.py')


def voice_toc(root):
    """The same files as PyInstaller TOC rows, added after Analysis. DATA keeps them unmodified."""
    return [(f'{target}/{Path(source).name}', source, 'DATA') for source, target in voice_datas(root)]


def voice_datas(root):
    """PyInstaller (source, destination directory) pairs. The build scripts stage the bundle."""
    root = Path(root)
    bundle = root / 'build/speechcpp'
    pairs = []
    if bundle.is_dir():
        pairs += [(str(file), 'build/speechcpp') for file in bundle.iterdir() if file.is_file()]
        pairs += [(str(file), 'build/speechcpp/notices') for file in (bundle / 'notices').iterdir() if file.is_file()]
    for file in (root / 'integrations/rvc').iterdir():
        if file.is_file() and (file.suffix == '.py' or file.name.startswith(('LICENSE', 'README'))):
            pairs.append((str(file), 'integrations/rvc'))
    for name in CONTRACT:
        target = Path('src-python/models') / name
        pairs.append((str(root / target), target.parent.as_posix()))
    return pairs
