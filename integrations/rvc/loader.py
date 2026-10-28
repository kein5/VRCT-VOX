# SPDX-License-Identifier: MIT
"""Pinned, local-only RVC initialization in the optional worker process.

No inference dependencies are imported until source and asset checks pass.
The supplied runtime is executable software, not an untrusted plugin sandbox.
"""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

COMMIT = '81eed5e8f68b6bed1789f682fe78cdd324495afc'


def require_source(root):
    root = Path(root).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL,
                                       timeout=10).decode().strip()
    try:
        if git('rev-parse', 'HEAD') != COMMIT:
            raise ValueError()
        git('diff', '--no-ext-diff', '--quiet', 'HEAD', '--')
        tracked = set(git('ls-files', '*.py').splitlines())
        if any(str(file.relative_to(root)) not in tracked for file in root.rglob('*.py')):
            raise ValueError()
    except (ValueError, OSError, subprocess.SubprocessError):
        raise ValueError('vc_source_unverified') from None


def require_assets(root):
    root = Path(root).resolve()
    required = ['hubert_base/config.json', 'hubert_base/preprocessor_config.json',
                'hubert_base/pytorch_model.bin', 'rmvpe/rmvpe.pt']
    if any(not (root / name).is_file() or (root / name).stat().st_size == 0 for name in required):
        raise ValueError('vc_assets_missing')
    return root


def load_complete_state(model, supplied):
    import torch
    expected = model.state_dict()
    # RVC training exports may retain enc_q, which inference explicitly removes.
    selected = {k: v for k, v in supplied.items() if not k.startswith('enc_q.')}
    if (selected.keys() != expected.keys() or any(
            not torch.is_tensor(selected[k]) or selected[k].shape != v.shape
            or not torch.isfinite(selected[k]).all() for k, v in expected.items())):
        raise ValueError('vc_checkpoint_incomplete')
    model.load_state_dict(selected, strict=True)


class CheckedIndex:
    """Latch errors even when pinned upstream catches and hides search failures."""
    def __init__(self, index, rows):
        self.index, self.rows, self.failed, self.calls = index, rows, False, 0

    def search(self, values, k):
        import numpy as np
        try:
            score, ix = self.index.search(values, k)
            if (score.shape != (len(values), k) or ix.shape != score.shape
                    or not np.isfinite(score).all() or (score <= 0).any()
                    or (ix < 0).any() or (ix >= self.rows).any()):
                raise ValueError('vc_index_failed')
            self.calls += 1
            return score, ix
        except Exception:
            self.failed = True
            raise

    def require_success(self):
        if self.failed or not self.calls:
            raise ValueError('vc_index_failed')


def require_engine(engine):
    required = ('model', 'net_g', 'tgt_sr', 'version', 'if_f0', 'cache_pitch', 'cache_pitchf')
    if any(getattr(engine, key, None) is None for key in required):
        raise ValueError('vc_engine_initialization_failed')


def enforce_retrieval_errors(module):
    # In the pinned rtrvc.py, the retrieval try/except calls traceback.print_exc
    # before continuing. Search success alone cannot prove blending succeeded.
    # Replace only this module's traceback binding, not Python's global module.
    # The source pin is required: this is an adapter to a fixed internal hook.
    def fail():
        raise ValueError('vc_index_failed') from None
    module.traceback = SimpleNamespace(format_exc=module.traceback.format_exc, print_exc=fail)


def _synthesizer(path, device):
    import torch
    from infer.module import models
    cpt = torch.load(path, map_location='cpu', weights_only=True)
    version, f0 = cpt.get('version', 'v1'), cpt.get('f0', 1)
    if (version not in ('v1', 'v2') or type(f0) is not int or f0 not in (0, 1)
            or cpt['config'][-1] not in (32000, 40000, 48000)):
        raise ValueError('vc_engine_format_invalid')
    config = list(cpt['config'])
    config[-3] = cpt['weight']['emb_g.weight'].shape[0]
    name = 'SynthesizerTrnMs' + ('256' if version == 'v1' else '768') + 'NSFsid'
    ctor = getattr(models, name + ('' if f0 else '_nono'))
    model = ctor(*config, **({'is_half': False} if f0 else {}))
    del model.enc_q
    load_complete_state(model, cpt['weight'])
    model = model.float().eval().to(device)
    model.remove_weight_norm()
    return model, cpt


def create_engine(engine_path, assets, model, index, pitch, index_rate):
    engine_path = Path(engine_path).resolve()
    require_source(engine_path)
    assets = require_assets(assets)
    if not Path(model).is_file() or (index_rate and not Path(index).is_file()):
        raise ValueError('vc_model_missing')
    for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY',
                'TORCH_FORCE_WEIGHTS_ONLY_LOAD'):
        os.environ[key] = '1'
    os.environ['RVC_CUDA_GRAPH'] = '0'
    sys.path.insert(0, str(engine_path))
    # Upstream i18n resolves locale JSON against cwd. No application process chdir.
    os.chdir(engine_path)
    import torch
    import numpy as np
    from configs.config import get_device_dtype_sm
    from infer import hubert, rtrvc
    from infer.rmvpe import RMVPE
    if not (2, 7) <= tuple(int(x) for x in torch.__version__.split('.')[:2]):
        raise ValueError('vc_runtime_version_unsupported')
    device, dtype, _, _ = get_device_dtype_sm(0)
    config = SimpleNamespace(device=device, is_half=dtype == torch.float16)
    hubert.HUBERT_MODEL_PATH = assets / 'hubert_base'
    def load_hubert(device, is_half):
        model, info = hubert.HubertModelWithFinalProj.from_pretrained(
            str(hubert.HUBERT_MODEL_PATH), local_files_only=True, output_loading_info=True,
            torch_dtype=torch.float16 if is_half else torch.float32)
        if any(info.get(key) for key in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')):
            raise ValueError('vc_checkpoint_incomplete')
        return model.eval().to(device)
    rtrvc.load_hubert_model = load_hubert
    rtrvc.get_synthesizer = _synthesizer
    enforce_retrieval_errors(rtrvc)
    vc = rtrvc.RVC(pitch, 0, str(model), str(index), index_rate, config)
    require_engine(vc)
    if index_rate:
        features = 256 if vc.version == 'v1' else 768
        if (not hasattr(vc, 'index') or vc.index.ntotal < 8 or vc.index.d != features
                or vc.big_npy.shape != (vc.index.ntotal, features) or not np.isfinite(vc.big_npy).all()):
            raise ValueError('vc_index_failed')
        vc.index = CheckedIndex(vc.index, vc.index.ntotal)
    if vc.if_f0:
        vc.model_rmvpe = RMVPE(str(assets / 'rmvpe/rmvpe.pt'), config.is_half, device=device)
    return vc
