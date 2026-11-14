#!/usr/bin/env python3
"""Prepare the reference environment the conformance tests compare against.

Everything lands outside the repository (default: ~/.cache/vrct-vox/rvc-reference,
override with RVC_REFERENCE_DIR). Nothing here is shipped with the application.

  engine/   the reference implementation at the commit the application already pins
  assets/   HuBERT (Transformers format), RMVPE weights and the published RMVPE graph
  model/    a CC BY 4.0 v2 / 40 kHz / F0 voice model from the application's catalog
  audio/    two CC BY 4.0 16 kHz speech clips
  assets/eval/  speaker verification, speech recognition and naturalness models for
                objective_compare.py
  venv/     CPU PyTorch plus the hash-locked inference dependencies

Every download is pinned by SHA-256. Standard library only; needs `uv` on PATH.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_COMMIT = '81eed5e8f68b6bed1789f682fe78cdd324495afc'
ENGINE_URL = f'https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/archive/{ENGINE_COMMIT}.zip'
WEIGHTS = 'https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/e6d0c1a17da07c33557852f9dfa2bd44cc75737d/'
ECAPA = 'https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb/resolve/0f99f2d0ebe89ac095bcc5903c4dd8f72b367286/'
WHISPER = 'https://huggingface.co/openai/whisper-small/resolve/973afd24965f72e36ca33b3055d56a652f456b4d/'
VOICE = 'https://huggingface.co/Saisho-Utane/Saisho-Model-RVC/resolve/7a61b17e4f014fc5013a489f2b5cd3a7ee9e2b1a/'
# (url, path under the reference directory, bytes, sha256)
FILES = (
    (WEIGHTS + 'hubert_base/config.json', 'assets/hubert_base/config.json', 1492,
     '0346950779dfb7f9316fa74ed846e2b8a22a08eedfdc5387b73f327cb1a4a7cf'),
    (WEIGHTS + 'hubert_base/preprocessor_config.json', 'assets/hubert_base/preprocessor_config.json', 225,
     '7c1976a680fb7acc757cd36fb08eef878fa36c70b4c9d2d595df9c608bbbbf0e'),
    (WEIGHTS + 'hubert_base/pytorch_model.bin', 'assets/hubert_base/pytorch_model.bin', 189206711,
     'cc8c20f4b90a520757260197a3ff2505705a7adbd20ad9eeaa4e1a9b38442ef5'),
    (WEIGHTS + 'rmvpe.pt', 'assets/rmvpe/rmvpe.pt', 181184272,
     '6d62215f4306e3ca278246188607209f09af3dc77ed4232efdd069798c4ec193'),
    (WEIGHTS + 'rmvpe.onnx', 'assets/rmvpe/rmvpe.onnx', 361688443,
     '5370e71ac80af8b4b7c793d27efd51fd8bf962de3a7ede0766dac0befa3660fd'),
    (VOICE + 'model.pth', 'model/model.pth', 57577658,
     '82312a29a3996a451aaa3d3776566cec85b47b5414fce53da82b2d66b04f3d35'),
    (VOICE + 'model.index', 'model/model.index', 278065619,
     'e9f7396e5db3077274c720d055e43abb8f1eac5609cbdf48b198ca4f4a35cad5'),
    # The published v2 / 40 kHz / F0 base generator (MIT); turned into an inference model by dump_reference.py.
    (WEIGHTS + 'pretrained_v2/f0G40k.pth', 'model/f0G40k.pth', 73106273,
     '3b2c44035e782c4b14ddc0bede9e2f4a724d025cd073f736d4f43708453adfcb'),
    # Objective comparison (objective_compare.py). Speaker verification: SpeechBrain ECAPA-TDNN on
    # VoxCeleb (Apache-2.0); only the embedding weights are used.
    (ECAPA + 'embedding_model.ckpt', 'assets/eval/ecapa/embedding_model.ckpt', 83316686,
     '0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2'),
    # Naturalness estimate: TorchAudio-Squim subjective model (BVCC and DAPS).
    ('https://download.pytorch.org/torchaudio/models/squim_subjective_bvcc_daps.pth',
     'assets/eval/squim/squim_subjective_bvcc_daps.pth', 377676157,
     'dd36e1e4a5e3b36a5e7c32c936097b57b3221663a0529704171a3bb792699718'),
    # Speech recognition: Whisper small (Apache-2.0).
    *[(WHISPER + name, f'assets/eval/whisper-small/{name}', size, digest) for name, size, digest in (
        ('model.safetensors', 966995080, '1d7734884874f1a1513ed9aa760a4f8e97aaa02fd6d93a3a85d27b2ae9ca596b'),
        ('config.json', 1967, 'e6a2b489da1b5aed65a8eb8d1e7466fa867ad5643a8bc138ba708bd56b2875c4'),
        ('generation_config.json', 3868, '71565b8ef50d0bf7a1193ed4bbed195b94e70c18894d81bba2f1233dcec3ab53'),
        ('preprocessor_config.json', 184990, '9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666'),
        ('tokenizer.json', 2480466, '27fc476bfe7f17299480be2273fc0608e4d5a99aba2ab5dec5374b4482d1a566'),
        ('tokenizer_config.json', 282683, '2a4c4281cf9f51ac6ccc406fdc711a087afe6530f671fa7b80953edc498275ce'),
        ('vocab.json', 835550, '8f680bba319e01a653d2e8a5dbc17a9157179e0576e6ce74ce0c06356c6e24f9'),
        ('merges.txt', 493869, '2df2990a395e35e8dfbc7511e08c12d56018d8d04691e0133e5d63b21e154dc6'),
        ('normalizer.json', 52666, 'bf1c507dc8724ca9cf9903640dacfb69dae2f00edee4f21ceba106a7392f26dd'),
        ('added_tokens.json', 34604, '9715fd2243b6f06a5858b5e32950d2853f73dd5bc201aafcf76f5082a2d8acd1'),
        ('special_tokens_map.json', 2194, 'e67ae3a0aaa99abcd9f187138e12db1f65c16a14761c50ef10eef2c174a7a691'))],
    # VOiCES corpus sample distributed with the torchaudio tutorials (CC BY 4.0).
    ('https://download.pytorch.org/torchaudio/tutorial-assets/Lab41-SRI-VOiCES-src-sp0307-ch127535-sg0042.wav',
     'audio/speech.wav', 108844, 'c65fcd726d6b08c82c1e5dc7558f863cd8d483e3ed2f4a7bcf271dc1865ada14'),
    # LibriSpeech utterance distributed with the torchaudio tutorials (CC BY 4.0); a second voice for listening.
    ('https://download.pytorch.org/torchaudio/tutorial-assets/ctc-decoding/1688-142285-0007.wav',
     'audio/speech2.wav', 451898, '67dfc27041e572bea27936e75eedc542ccf6f3af5cc251a0ab4e1e947d787fc8'),
)
TORCH = ('torch==2.11.0', 'torchaudio==2.11.0')
EXPORT = ('onnx==1.23.2', 'onnxscript==0.7.2', 'onnxruntime==1.32.0', 'speechbrain==1.1.2')


def reference_dir():
    override = os.environ.get('RVC_REFERENCE_DIR')
    if override:
        return Path(override)
    cache = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    return Path(cache) / 'vrct-vox' / 'rvc-reference'


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as reader:
        for block in iter(lambda: reader.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(url, target, size, digest):
    if target.exists() and target.stat().st_size == size and sha256(target) == digest:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    print(f'fetch {target.name} ({size} bytes)', flush=True)
    request = urllib.request.Request(url, headers={'User-Agent': 'rvc-reference-setup'})
    with urllib.request.urlopen(request) as reader, open(part, 'wb') as writer:
        shutil.copyfileobj(reader, writer, 1 << 20)
    found = sha256(part)
    if part.stat().st_size != size or found != digest:
        part.unlink()
        raise SystemExit(f'{target.name}: expected {size} bytes / {digest}, got {found}')
    part.replace(target)


def engine(root):
    target = root / 'engine'
    marker = target / '.commit'
    if marker.exists() and marker.read_text().strip() == ENGINE_COMMIT:
        return
    archive = root / 'engine.zip'
    print('fetch engine source', flush=True)
    urllib.request.urlretrieve(ENGINE_URL, archive)
    shutil.rmtree(target, ignore_errors=True)
    prefix = f'Retrieval-based-Voice-Conversion-WebUI-{ENGINE_COMMIT}/'
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            relative = Path(info.filename[len(prefix):])
            if relative.is_absolute() or '..' in relative.parts:
                raise SystemExit(f'unsafe archive entry: {info.filename}')
            out = target / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(source.read(info))
    archive.unlink()
    marker.write_text(ENGINE_COMMIT + '\n')


def venv(root):
    python = root / 'venv' / 'bin' / 'python'
    marker = root / 'venv' / '.ready'
    wanted = '\n'.join(TORCH + EXPORT) + '\n'
    if marker.exists() and marker.read_text() == wanted:
        return python
    uv = shutil.which('uv')
    if not uv:
        raise SystemExit('uv is required to create the reference environment')
    run = lambda *argv: subprocess.run(argv, check=True)
    run(uv, 'venv', '--python', '3.12', '--clear', str(root / 'venv'))
    run(uv, 'pip', 'install', '--python', str(python), '--index-url',
        'https://download.pytorch.org/whl/cpu', *TORCH)
    run(uv, 'pip', 'install', '--python', str(python), '--require-hashes', '-r',
        str(REPO_ROOT / 'integrations' / 'rvc' / 'requirements.lock'))
    run(uv, 'pip', 'install', '--python', str(python), *EXPORT)
    marker.write_text(wanted)
    return python


def main():
    root = reference_dir()
    root.mkdir(parents=True, exist_ok=True)
    engine(root)
    for url, relative, size, digest in FILES:
        fetch(url, root / relative, size, digest)
    python = venv(root)
    print(f'reference directory: {root}')
    print(f'reference python:    {python}')


if __name__ == '__main__':
    sys.exit(main())
