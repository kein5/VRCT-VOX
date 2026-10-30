# SPDX-License-Identifier: GPL-3.0-only
"""Offline adaptation of jiaheguo521/seed-vc-realtime 58d0ca3.

Model construction follows realtime_vc_engine.py; downloads, incomplete state
loads, alternative model families and automatic device fallback are excluded.
"""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from tools.seedvc_artifacts import DEFAULT_MANIFEST
from .offline import OfflineAssets, require_complete_state, validate_reference


def migrate_seed_state(expected, supplied):
    """Migrate two deterministic buffers in the pinned legacy tiny checkpoint.

    Upstream 1a639856 cached timestep frequencies; c32991ca enlarged positions.
    Never fill absent learned parameters from an initialized model.
    """
    import torch
    result = dict(supplied)
    freq, pos = 'estimator.t_embedder.freqs', 'estimator.input_pos'
    if freq in result and (result[freq].dtype != expected[freq].dtype
                          or not torch.equal(result[freq], expected[freq])):
        raise ValueError('checkpoint_buffer_invalid: freqs')
    old = result.get(pos)
    if (old is None or old.dtype != torch.int64 or old.shape != (8192,)
            or not torch.equal(old, torch.arange(8192))):
        raise ValueError('checkpoint_buffer_invalid: input_pos')
    result[freq], result[pos] = expected[freq], expected[pos]
    require_complete_state(expected, result)
    return result


def remap_campplus_state(supplied):
    """Apply CAMPPlus DTDNN.py:113–130's legacy name migration before audit."""
    result = {}
    for name, value in supplied.items():
        if name.startswith(('xvector.stats.', 'xvector.dense.')):
            name = name.removeprefix('xvector.')
        if name in result:
            raise ValueError('checkpoint_duplicate_key')
        result[name] = value
    return result


class LocalModelLoader:
    def __init__(self, assets, engine_root):
        self.assets = assets
        self.engine_root = engine_root
        self.checkpoints = {}

    def load_models(self, engine, args):
        import torch
        import yaml
        from audio_modules.commons import build_model, recursive_munch
        from audio_modules.campplus.DTDNN import CAMPPlus
        from audio_modules.hifigan.generator import HiFTGenerator
        from audio_modules.hifigan.f0_predictor import ConvRNNF0Predictor
        from audio_modules.audio import mel_spectrogram
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2Model

        def weights(repo, name):
            return torch.load(self.assets.file(repo, name), map_location='cpu', weights_only=True)

        def complete(name, model, supplied):
            result = require_complete_state(model.state_dict(), supplied)
            model.load_state_dict({key: supplied[key] for key in model.state_dict()}, strict=True)
            model.eval().to(engine.device)
            return result

        config = yaml.safe_load(self.assets.file(
            'Plachta/Seed-VC', 'config_dit_mel_seed_uvit_xlsr_tiny.yml').read_text())
        params = recursive_munch(config['model_params'])
        if params.vocoder.type != 'hifigan' or params.speech_tokenizer.type != 'xlsr':
            raise ValueError('unsupported_model_family')
        params.dit_type = 'DiT'
        model = build_model(params, stage='DiT')
        supplied = weights('Plachta/Seed-VC', 'DiT_uvit_tat_xlsr_ema.pth')['net']
        self.checkpoints['seed'] = {}
        for key in model:
            state = {k.removeprefix('module.'): v for k, v in supplied.get(key, {}).items()}
            if key == 'cfm':
                state = migrate_seed_state(model[key].state_dict(), state)
            self.checkpoints['seed'][key] = complete(key, model[key], state)
        self.checkpoints['seed']['regenerated_buffers'] = {
            'estimator.t_embedder.freqs': 'canonical float32 formula',
            'estimator.input_pos': 'validated int64 arange(8192) -> arange(16384)',
        }
        model.cfm.estimator.setup_caches(max_batch_size=1, max_seq_length=8192)

        campplus = CAMPPlus(feat_dim=80, embedding_size=192)
        self.checkpoints['campplus'] = complete('campplus', campplus,
            remap_campplus_state(weights('funasr/campplus', 'campplus_cn_common.bin')))
        hift_config = yaml.safe_load((self.engine_root / 'configs/hifigan.yml').read_text())
        hift = HiFTGenerator(**hift_config['hift'],
            f0_predictor=ConvRNNF0Predictor(**hift_config['f0_predictor']))
        self.checkpoints['hift'] = complete('hift', hift,
            weights('FunAudioLLM/CosyVoice-300M', 'hift.pt'))

        xlsr_dir = self.assets.file('facebook/wav2vec2-xls-r-300m', 'pytorch_model.bin').parent
        feature = Wav2Vec2FeatureExtractor.from_pretrained(str(xlsr_dir), local_files_only=True)
        xlsr, info = Wav2Vec2Model.from_pretrained(str(xlsr_dir), local_files_only=True,
            use_safetensors=False, weights_only=True, output_loading_info=True)
        if info['missing_keys'] or info['mismatched_keys'] or info['error_msgs']:
            raise ValueError(f'checkpoint_incomplete: xlsr {info}')
        self.checkpoints['xlsr'] = {'missing': 0, 'unused': len(info['unexpected_keys'])}
        xlsr.encoder.layers = xlsr.encoder.layers[:params.speech_tokenizer.output_layer]
        xlsr.eval().to(engine.device).half()

        def semantic_fn(waves_16k):
            inputs = feature([x.cpu().numpy() for x in waves_16k], return_tensors='pt',
                return_attention_mask=True, padding=True, sampling_rate=16000).to(engine.device)
            with torch.no_grad():
                return xlsr(inputs.input_values.half()).last_hidden_state.float()

        spect = config['preprocess_params']['spect_params']
        mel_args = dict(n_fft=spect['n_fft'], win_size=spect['win_length'],
            hop_size=spect['hop_length'], num_mels=spect['n_mels'],
            sampling_rate=config['preprocess_params']['sr'], fmin=spect.get('fmin', 0),
            fmax=None if spect.get('fmax', 'None') == 'None' else 8000, center=False)

        def to_mel(x):
            return mel_spectrogram(x, **mel_args)

        return model, semantic_fn, hift, campplus, to_mel, mel_args

    def load_vad(self, engine):
        import torch
        import yaml
        from funasr import AutoModel

        config = yaml.safe_load(self.assets.file('funasr/fsmn-vad', 'config.yaml').read_text())
        config['frontend_conf']['cmvn_file'] = str(self.assets.file('funasr/fsmn-vad', 'am.mvn'))
        # model_conf bypasses all hub resolution. Build without init_param because
        # FunASR's checkpoint loader silently fills absent weights from random init.
        vad = AutoModel(**config, device=str(engine.device), disable_update=True,
            trust_remote_code=False, disable_pbar=True, log_level='ERROR')
        supplied = torch.load(self.assets.file('funasr/fsmn-vad', 'model.pt'),
            map_location='cpu', weights_only=True)
        self.checkpoints['vad'] = require_complete_state(vad.model.state_dict(), supplied)
        vad.model.load_state_dict({k: supplied[k] for k in vad.model.state_dict()}, strict=True)
        vad.model.eval()
        return vad


def create_engine(engine_root, assets_root, reference):
    # No heavy imports before consented inputs have been checked in full.
    metadata = validate_reference(reference)
    assets = OfflineAssets(json.loads(DEFAULT_MANIFEST.read_text()), assets_root)
    engine_root = Path(engine_root).resolve()
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    sys.path.insert(0, str(engine_root))
    import torch
    from realtime_vc_engine import RealtimeVCEngine
    if not torch.cuda.is_available():
        raise RuntimeError('cuda_required_for_this_poc')
    loader = LocalModelLoader(assets, engine_root)
    args = SimpleNamespace(gpu=0, fp16=True, checkpoint_path=None, config_path=None)
    engine = RealtimeVCEngine(args, model_loader=loader, enumerate_devices=False)
    engine.set_config(reference_audio_path=str(Path(reference).resolve()))
    return engine, loader.checkpoints, metadata
