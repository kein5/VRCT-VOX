"""Reviewed public artifacts; update revision, bytes and hash together, never at runtime."""
from dataclasses import dataclass, replace
import re

CATALOG_VERSION = '2026-10-30.2'


@dataclass(frozen=True)
class Artifact:
    filename: str
    size: int
    sha256: str
    role: str


@dataclass(frozen=True)
class Model:
    id: str
    target: str
    name: str
    provider: str
    repo: str
    revision: str
    license: str
    licenses: tuple
    notice: str
    artifacts: tuple


IRODORI_REV = '9db7da1bec3d1069ef8e29732e0497be60c7b047'
QWEN_REV = 'fd9df9364613a92a86b4137074bc281204823033'
RVC_REV = '7a61b17e4f014fc5013a489f2b5cd3a7ee9e2b1a'
CATALOG = (
    Model('irodori-v41-f16', 'japanese', 'Irodori-TTS v4.1 Small MF · F16', 'Aratako / sakasegawa',
          'sakasegawa/Irodori-TTS-v4.1-Small-MF-GGUF', IRODORI_REV, 'MIT + Apache-2.0', (
              f'https://huggingface.co/sakasegawa/Irodori-TTS-v4.1-Small-MF-GGUF/blob/{IRODORI_REV}/README.md',
              f'https://huggingface.co/sakasegawa/Irodori-TTS-v4.1-Small-MF-GGUF/blob/{IRODORI_REV}/LICENSE-MIT',
              f'https://huggingface.co/sakasegawa/Irodori-TTS-v4.1-Small-MF-GGUF/blob/{IRODORI_REV}/LICENSE-APACHE-2.0'),
          'irodori', (Artifact('Irodori-TTS-866M-MF-v4.1-F16.gguf', 1920321792,
                              'e237dc3eefe469b8bba87872beacf12fb7fe00dbdf85767edca8ec04ab910d13', 'model'),)),
    Model('qwen3-06b-q8', 'multilingual', 'Qwen3-TTS 12Hz 0.6B CustomVoice · Q8_0', 'Qwen / sakasegawa',
          'sakasegawa/Qwen3-TTS-12Hz-0.6B-CustomVoice-GGUF', QWEN_REV, 'Apache-2.0', (
              f'https://huggingface.co/sakasegawa/Qwen3-TTS-12Hz-0.6B-CustomVoice-GGUF/blob/{QWEN_REV}/README.md',
              'https://www.apache.org/licenses/LICENSE-2.0'),
          'qwen', (Artifact('Qwen3-TTS-12Hz-0.6B-CustomVoice-Q8_0.gguf', 1213534464,
                           'f606ea3981aa42762b16db9a94826d2d560eb60f0b102001618f40d5a2f78cc6', 'model'),)),
    Model('rvc-saisho', 'rvc', 'Saisho Utane · RVC v2', 'Saisho Utane',
          'Saisho-Utane/Saisho-Model-RVC', RVC_REV, 'CC BY 4.0', (
              f'https://huggingface.co/Saisho-Utane/Saisho-Model-RVC/blob/{RVC_REV}/README.md',
              'https://creativecommons.org/licenses/by/4.0/'),
          'rvc', (
              Artifact('model.pth', 57577658, '82312a29a3996a451aaa3d3776566cec85b47b5414fce53da82b2d66b04f3d35', 'model'),
              Artifact('model.index', 278065619, 'e9f7396e5db3077274c720d055e43abb8f1eac5609cbdf48b198ca4f4a35cad5', 'index'))),
)

CATALOG = (*CATALOG,
    replace(CATALOG[0], id='irodori-v41-q8', name='Irodori-TTS v4.1 Small MF · Q8_0', artifacts=(
        Artifact('Irodori-TTS-866M-MF-v4.1-Q8_0.gguf', 1207133984,
                 '2d161b0bbcd74f906f6b07e03d031075f8ae916db1b8bd4daf16cb37b451086a', 'model'),)),
    replace(CATALOG[1], id='qwen3-06b-q5', name='Qwen3-TTS 12Hz 0.6B CustomVoice · Q5_K', artifacts=(
        Artifact('Qwen3-TTS-12Hz-0.6B-CustomVoice-Q5_K.gguf', 873894144,
                 '4bb9ba9e822ab614798c416c7f0187994f349be41221966fa911aca24f237930', 'model'),)))


def validate_catalog(catalog):
    ids = set()
    for model in catalog:
        if (model.id in ids or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', model.id)
                or not re.fullmatch(r'[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+', model.repo)
                or not re.fullmatch(r'[0-9a-f]{40}', model.revision)
                or model.target not in ('japanese', 'multilingual', 'rvc') or not model.artifacts):
            raise ValueError('catalog_invalid')
        ids.add(model.id)
        names, roles = set(), set()
        for artifact in model.artifacts:
            if (not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*\.(gguf|pth|index)', artifact.filename) or '..' in artifact.filename
                    or artifact.filename in names or artifact.role in roles or artifact.role not in ('model', 'index')
                    or type(artifact.size) is not int or artifact.size <= 0
                    or not re.fullmatch(r'[0-9a-f]{64}', artifact.sha256)):
                raise ValueError('catalog_invalid')
            names.add(artifact.filename); roles.add(artifact.role)
