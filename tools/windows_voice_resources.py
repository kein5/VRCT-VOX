"""Files the Windows sidecar ships for speech.cpp and the external voice workers.

The fixed speech.cpp bundle comes from speechcpp_bundle.py. External inference
interpreters cannot read the frozen sidecar's PYZ, so the engine adapters and their
small, dependency-free contract modules ship as ordinary files. They get their own
folder: the worker runs from it, and _internal holds the sidecar's Python 3.11 extension
modules, which would shadow the standard library of the worker's own Python.
"""
import importlib.metadata
import json
from pathlib import Path
import re

CONTRACT =('__init__.py', 'owned_child.py', 'voice_conversion/__init__.py',
            'voice_conversion/protocol.py', 'voice_conversion/settings.py')
WORKER = 'voice_worker'
ENGINES = ('rvc', 'seed_vc')
# The sidecar sets a runtime up from these; the requirements for Linux stay out.
SETUP_FILES = {'rvc': ('requirements-cuda-windows.lock', 'requirements-windows.lock'),
               'seed_vc': ('requirements-windows.lock', 'offline-loader.patch')}
# integrations/seed_vc reads these through ROOT relative paths.
SEED_SUPPORT = ('tools/seedvc_artifacts.py', 'docs/voice-stack/seed-vc-poc-artifacts.json')
REQUIRED = ('build/speechcpp/speech.exe', 'build/speechcpp/bundle.json',
            f'{WORKER}/integrations/rvc/live_worker.py', f'{WORKER}/integrations/rvc/requirements-windows.lock',
            f'{WORKER}/integrations/seed_vc/live_worker.py', f'{WORKER}/tools/seedvc_artifacts.py',
            f'{WORKER}/src-python/models/voice_conversion/protocol.py', 'licenses/VRCT/NOTICE.md')


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
    for engine in ENGINES:
        source = root / 'integrations' / engine
        if not source.is_dir():
            continue
        for file in source.iterdir():
            if file.is_file() and (file.suffix == '.py' or file.name.startswith(('LICENSE', 'README'))
                                   or file.name in SETUP_FILES[engine]):
                pairs.append((str(file), f'{WORKER}/integrations/{engine}'))
    for name in SEED_SUPPORT:
        if (root / name).is_file():
            pairs.append((str(root / name), f'{WORKER}/{Path(name).parent.as_posix()}'))
    for name in CONTRACT:
        target = Path('src-python/models') / name
        pairs.append((str(root / target), f'{WORKER}/{target.parent.as_posix()}'))
    return pairs


def notice_toc():
    """The license files of the build environment, as NOTICE.md says the build carries.

    Run this inside that environment. Linux collects the same set in build_linux.py.
    """
    rows = []
    for package in importlib.metadata.distributions():
        name = f"{package.metadata['Name']}-{package.version}"
        for file in package.files or []:
            if '.dist-info' not in str(file) and '.egg-info' not in str(file):
                continue
            if not any(part.lower().startswith(('license', 'copying', 'notice', 'authors')) for part in file.parts):
                continue
            source = Path(package.locate_file(file))
            if source.is_file() and '..' not in file.parts and not file.is_absolute():
                rows.append((f'licenses/python/{name}/{Path(file).as_posix()}', str(source), 'DATA'))
    return rows


def sidecar_version(root):
    """The name Windows shows when it asks whether this exe may use the microphone.

    With no version resource the question reads "Allow   to access your microphone?".
    Someone who leaves that unanswered is refused from then on, with no further question.
    Returns the path of a PyInstaller version file.
    """
    root = Path(root)
    version = json.loads((root / 'package.json').read_text(encoding='utf-8'))['version']
    numbers = tuple(int(part) for part in re.findall(r'\d+', version)[:4])
    numbers += (0,) * (4 - len(numbers))
    strings = (('FileDescription', 'VRCT-VOX'), ('ProductName', 'VRCT-VOX'), ('FileVersion', version),
               ('ProductVersion', version), ('OriginalFilename', 'vrct-vox-sidecar.exe'))
    rows = ', '.join(f'StringStruct({name!r}, {value!r})' for name, value in strings)
    path = root / 'build/sidecar-version.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"VSVersionInfo(ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}), "
                    f"kids=[StringFileInfo([StringTable('040904B0', [{rows}])]), "
                    f"VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n", encoding='utf-8')
    return str(path)


def missing_files(internal):
    """What the app needs from a frozen _internal tree; the specs themselves tolerate a gap."""
    internal = Path(internal)
    missing = [name for name in REQUIRED if not (internal / name).is_file()]
    if not any((internal / 'licenses/python').glob('*/*')):
        missing.append('licenses/python')
    return missing
