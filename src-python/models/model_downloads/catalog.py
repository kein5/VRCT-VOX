"""Reviewed public artifacts; update revision, bytes and hash together, never at runtime."""
from dataclasses import dataclass, replace
import re
from urllib.parse import quote

CATALOG_VERSION = '2026-11-01.4'


@dataclass(frozen=True)
class Artifact:
    filename: str
    size: int
    sha256: str
    role: str
    # (repo, revision, path) when the file comes from another pinned repository
    # or has a different name there. Empty: <model.repo>@<model.revision>/<filename>.
    remote: tuple = ()


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
# Files before this revision hold no custom vocabulary; needs speech.cpp 0.9.4 or later.
HAAS_REV = '6b965d5007ba780585de51549d57a8c1c0d67c7e'
# The revision speech.cpp 0.10.0's own catalog pins for qwen3-asr-0.6b and silero-vad.
QWEN_ASR_REV = 'ee78f8709547f39bea3b924a16c72403826cac92'
SILERO_REV = '7fcb7aa2a70c312f8579fc987b3e1cdecf9321ca'
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
    Model('haas-ja-q8', 'asr', 'Haas-ja v1.0 · Q8_0', 'Third Intelligence / sakasegawa',
          'sakasegawa/Haas-ja-v1.0-GGUF', HAAS_REV, 'Apache-2.0', (
              f'https://huggingface.co/sakasegawa/Haas-ja-v1.0-GGUF/blob/{HAAS_REV}/README.md',
              f'https://huggingface.co/sakasegawa/Haas-ja-v1.0-GGUF/blob/{HAAS_REV}/LICENSE'),
          'haas', (Artifact('Haas-616M-ja-v1.0-Q8_0.gguf', 656381472,
                           'cd5f60b2f1c411404b83fca4a65e3ce30a26d9e951b6a346529e65f22758afeb', 'model'),)),
    # Q8_0 is the file speech.cpp fetches for this name. On Common Voice 8.0 ja its
    # CER is 11.89% against 12.49% for Q5_K, for 0.25 GB more; it detects the language.
    Model('qwen3-asr-06b-q8', 'asr', 'Qwen3-ASR 0.6B · Q8_0 (30 languages)', 'Qwen / sakasegawa',
          'sakasegawa/Qwen3-ASR-0.6B-GGUF', QWEN_ASR_REV, 'Apache-2.0', (
              f'https://huggingface.co/sakasegawa/Qwen3-ASR-0.6B-GGUF/blob/{QWEN_ASR_REV}/README.md',
              'https://www.apache.org/licenses/LICENSE-2.0'),
          'qwen_asr', (Artifact('Qwen3-ASR-0.6B-Q8_0.gguf', 841502336,
                               '416e10c15b4a3d9002bd337d18fc450233fdf68502b6e10d1379d2789838afd0', 'model'),)),
    # Applies to the asr profile's vad_model, not to its recognition model.
    Model('silero-vad-v62', 'vad', 'Silero VAD v6.2 · F32', 'Silero Team / sakasegawa',
          'sakasegawa/silero-vad-GGUF', SILERO_REV, 'MIT', (
              f'https://huggingface.co/sakasegawa/silero-vad-GGUF/blob/{SILERO_REV}/README.md',
              f'https://huggingface.co/sakasegawa/silero-vad-GGUF/blob/{SILERO_REV}/LICENSE'),
          'silero', (Artifact('silero-vad-309K-v6.2-F32.gguf', 1238624,
                             '2fc312514e5fc4fa4ffd02b25c76a4853fa4130e8fb9777d01502183b01238cb', 'model'),)),
)

CATALOG = (*CATALOG,
    replace(CATALOG[0], id='irodori-v41-q8', name='Irodori-TTS v4.1 Small MF · Q8_0', artifacts=(
        Artifact('Irodori-TTS-866M-MF-v4.1-Q8_0.gguf', 1207133984,
                 '2d161b0bbcd74f906f6b07e03d031075f8ae916db1b8bd4daf16cb37b451086a', 'model'),)),
    replace(CATALOG[1], id='qwen3-06b-q5', name='Qwen3-TTS 12Hz 0.6B CustomVoice · Q5_K', artifacts=(
        Artifact('Qwen3-TTS-12Hz-0.6B-CustomVoice-Q5_K.gguf', 873894144,
                 '4bb9ba9e822ab614798c416c7f0187994f349be41221966fa911aca24f237930', 'model'),)))


TARGETS = ('japanese', 'multilingual', 'asr', 'vad', 'rvc', 'ocr')
# Where an applied file goes: (speech server profile, settings field). RVC is separate.
SPEECH_FIELDS = {'japanese': ('japanese', 'model'), 'multilingual': ('multilingual', 'model'),
                 'asr': ('asr', 'model'), 'vad': ('asr', 'vad_model')}


# --- OCR (chat reading) models: begin -----------------------------------------
# Official PaddleOCR ONNX exports, Apache-2.0. One entry per download the user
# consents to; det and rec live in separate upstream repos, so their files carry
# remote pins and are stored under local names. RapidOCR needs the recogniser's
# character list, which PaddleOCR ships in inference.yml (PostProcess.character_dict).
# Changing any pin below changes the files in <id>/<revision>/: bump the id too.
OCR_DET_REPO, OCR_DET_REV = 'PaddlePaddle/PP-OCRv6_small_det_onnx', '28fe5895c24fd108c19eb3e8479f4ab385fbfc62'
OCR_REC_REPO, OCR_REC_REV = 'PaddlePaddle/PP-OCRv6_small_rec_onnx', 'b8f84f0b80c529de40b4fbb3544b84fa7233a513'
APACHE_2 = 'https://www.apache.org/licenses/LICENSE-2.0'


def _ocr_script(id, name, repo, revision, onnx, yml):
    return Model(id, 'ocr', name, 'PaddlePaddle (PaddleOCR)', repo, revision, 'Apache-2.0', (
        f'https://huggingface.co/{repo}/blob/{revision}/README.md', APACHE_2), 'ppocr', (
        Artifact('rec.onnx', onnx[0], onnx[1], 'rec', (repo, revision, 'inference.onnx')),
        Artifact('rec.yml', yml[0], yml[1], 'dict', (repo, revision, 'inference.yml'))))


OCR_CATALOG = (
    Model('ppocrv6-small', 'ocr', 'PP-OCRv6 small · Japanese, English, Chinese, Latin', 'PaddlePaddle (PaddleOCR)',
          OCR_REC_REPO, OCR_REC_REV, 'Apache-2.0', (
              f'https://huggingface.co/{OCR_REC_REPO}/blob/{OCR_REC_REV}/README.md',
              f'https://huggingface.co/{OCR_DET_REPO}/blob/{OCR_DET_REV}/README.md', APACHE_2),
          'ppocr', (
              Artifact('det.onnx', 9880512, 'd73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e', 'det',
                       (OCR_DET_REPO, OCR_DET_REV, 'inference.onnx')),
              Artifact('rec.onnx', 21159378, '5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634', 'rec',
                       (OCR_REC_REPO, OCR_REC_REV, 'inference.onnx')),
              Artifact('rec.yml', 150579, 'ab078671bb49f06228eadccd34f1bb501e157f7a047095ffb943ba81512c77d1', 'dict',
                       (OCR_REC_REPO, OCR_REC_REV, 'inference.yml')))),
    # Scripts PP-OCRv6 small does not cover. They reuse the detector above.
    _ocr_script('ppocrv5-korean', 'PP-OCRv5 mobile · Korean', 'PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx',
                '5c6f574b8e2230adf4287b33e736d71b9fabd28e',
                (13418787, '92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08'),
                (96039, 'f757fa1c40e99edcf27e9cce879b93eb2a51fa46f5ef39095689b8c37dd75998')),
    _ocr_script('ppocrv5-cyrillic', 'PP-OCRv5 mobile · Cyrillic', 'PaddlePaddle/cyrillic_PP-OCRv5_mobile_rec_onnx',
                '2cef88145434beb8afa9dd82d77d799eb1ad7b29',
                (8048799, '5371ee1ddaa7983cc62d0818d99e982b6804638c85e4f960d59a574094e172e5'),
                (6991, '5c76cc91fa98410178a09f498db10050d0ec1634a660053d3005ab7be581f501')),
    _ocr_script('ppocrv5-thai', 'PP-OCRv5 mobile · Thai', 'PaddlePaddle/th_PP-OCRv5_mobile_rec_onnx',
                '1d4adbbafb1034a2fd6618498575b81ea7b69f69',
                (7891015, '27618be66018f8598ac0a526a593f9f1cebf794e7eded93428e8fb016e537f5f'),
                (4667, 'f6ba7fefc38ca1ff398ddafa75d67d16e0b3757c4e6c833adffee98a981766c9')),
    _ocr_script('ppocrv5-arabic', 'PP-OCRv5 mobile · Arabic', 'PaddlePaddle/arabic_PP-OCRv5_mobile_rec_onnx',
                '14aaedcd75825982689ecf5cd64ab33ee083215a',
                (7998947, '799113ebf267fbe742deb99eb36e8d42c9ddc5291ceacf92add41b4d52a59110'),
                (6165, '21368419e6c016c31db55d316d59e11c128e1913e6e6fe10287084710043d3a6')),
    _ocr_script('ppocrv5-devanagari', 'PP-OCRv5 mobile · Devanagari', 'PaddlePaddle/devanagari_PP-OCRv5_mobile_rec_onnx',
                '251aec19e36739540d35e2cc943f6aa7503b98e5',
                (7912311, 'cb789212ce96c69d3e74728ae4309d179281d68cb3945d0616b67cafab41c986'),
                (5027, '9bd172dd26440c8ce94d1cde5d5baea6aefdc7cf3c5c8492e0beedef656d4e54')),
)
CATALOG = (*CATALOG, *OCR_CATALOG)

# VRCT-VOX's own chatbox detector (YOLOX-Tiny, MIT), trained from VRCT-VOX's own
# frames with tools/chatbox_lab. It is not the upstream VRCT detector
# (models/ocr/onnx/chatbox_yolox_tiny.onnx), which may never be offered here:
# the file name differs on purpose, and models/ocr/ocr_chatbox_detector.py only
# loads this entry's hash-verified download.
# Published by the maintainer from tools/chatbox_lab. A new upload needs a new
# revision, size and hash here, and a CATALOG_VERSION bump.
DETECTOR_MODEL_ID = 'vrct-vox-chatbox-detector'
DETECTOR_FILE_NAME = 'vrct_vox_chatbox_yolox_tiny.onnx'
DETECTOR_REPO = 'kein5/vrct-vox-chatbox-detector'
DETECTOR_REVISION = '9c460bf687da59e069ed76f8ee9cd3157dab7ae1'
DETECTOR_SIZE = 20184371
DETECTOR_SHA256 = '2fab797de821cc5d1985ede27acc55dd97ea46a1ce2b6aee5c775347e5a501f6'
DETECTOR_CATALOG = (
    Model(DETECTOR_MODEL_ID, 'ocr', 'VRCT-VOX chatbox detector · YOLOX-Tiny', 'VRCT-VOX',
          DETECTOR_REPO, DETECTOR_REVISION, 'MIT', (
              f'https://huggingface.co/{DETECTOR_REPO}/blob/{DETECTOR_REVISION}/README.md',
              f'https://huggingface.co/{DETECTOR_REPO}/blob/{DETECTOR_REVISION}/LICENSE'),
          'chatbox', (Artifact(DETECTOR_FILE_NAME, DETECTOR_SIZE, DETECTOR_SHA256, 'detector'),)),
)
CATALOG = (*CATALOG, *DETECTOR_CATALOG)
# --- OCR (chat reading) models: end -------------------------------------------


def artifact_url(model, artifact):
    repo, revision, path = artifact.remote or (model.repo, model.revision, artifact.filename)
    return f'https://huggingface.co/{repo}/resolve/{revision}/{quote(path)}'


def validate_catalog(catalog):
    ids = set()
    for model in catalog:
        if (model.id in ids or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', model.id)
                or not re.fullmatch(r'[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+', model.repo)
                or not re.fullmatch(r'[0-9a-f]{40}', model.revision)
                or model.target not in TARGETS or not model.artifacts):
            raise ValueError('catalog_invalid')
        ids.add(model.id)
        names, roles = set(), set()
        ocr = model.target == 'ocr'
        suffixes, allowed_roles = (('onnx', 'yml'), ('det', 'rec', 'dict', 'detector')) if ocr else (('gguf', 'pth', 'index'), ('model', 'index'))
        for artifact in model.artifacts:
            if (not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*\.(' + '|'.join(suffixes) + ')', artifact.filename)
                    or '..' in artifact.filename
                    or artifact.filename in names or artifact.role in roles or artifact.role not in allowed_roles
                    or type(artifact.size) is not int or artifact.size <= 0
                    or not re.fullmatch(r'[0-9a-f]{64}', artifact.sha256)
                    or not _valid_remote(artifact.remote)):
                raise ValueError('catalog_invalid')
            names.add(artifact.filename); roles.add(artifact.role)


def _valid_remote(remote):
    if remote == ():
        return True
    return (isinstance(remote, tuple) and len(remote) == 3 and all(isinstance(part, str) for part in remote)
            and re.fullmatch(r'[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+', remote[0]) is not None
            and re.fullmatch(r'[0-9a-f]{40}', remote[1]) is not None
            and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', remote[2]) is not None and '..' not in remote[2])
