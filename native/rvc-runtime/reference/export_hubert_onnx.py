#!/usr/bin/env python3
"""Export the HuBERT feature extractor to ONNX for the runtime.

The checkpoint is the Transformers-format `hubert_base` the application already pins
(weights: a ContentVec-family HuBERT base plus the 768 -> 256 `final_proj` layer). The
graph is built from the stock `transformers.HubertModel`; nothing of the reference
engine is involved.

    input   audio        [1, samples]      16 kHz, not normalised (see preprocessor_config.json)
    output  features_v2  [1, frames, 768]  last encoder layer
    output  features_v1  [1, frames, 256]  ninth encoder layer through final_proj

Run with the reference environment's interpreter; writes <reference>/assets/hubert_base/hubert.onnx.
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch
from transformers import HubertConfig, HubertModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_reference import reference_dir  # noqa: E402


class Features(torch.nn.Module):
    def __init__(self, folder):
        super().__init__()
        config = HubertConfig.from_pretrained(folder)
        self.hubert = HubertModel(config)
        self.final_proj = torch.nn.Linear(config.hidden_size, config.classifier_proj_size)
        state = torch.load(folder / 'pytorch_model.bin', map_location='cpu', weights_only=True)
        state = {key: value.float() for key, value in state.items()}
        projection = {key.removeprefix('final_proj.'): state.pop(key) for key in list(state) if key.startswith('final_proj.')}
        self.final_proj.load_state_dict(projection, strict=True)
        missing, unexpected = self.hubert.load_state_dict(state, strict=False)
        # The masking embedding is only used in training; anything else must line up.
        problems = [key for key in missing if key != 'masked_spec_embed'] + list(unexpected)
        if problems:
            raise SystemExit(f'checkpoint does not match the stock HuBERT layout: {problems[:5]}')

    def forward(self, audio):
        output = self.hubert(audio, output_hidden_states=True)
        return output.last_hidden_state, self.final_proj(output.hidden_states[9])


def main():
    folder = reference_dir() / 'assets' / 'hubert_base'
    if json.loads((folder / 'preprocessor_config.json').read_text()).get('do_normalize'):
        raise SystemExit('this checkpoint expects normalised input; the runtime does not normalise')
    model = Features(folder).eval()
    target = folder / 'hubert.onnx'
    example = torch.zeros(1, 16000)
    with torch.no_grad():
        torch.onnx.export(model, (example,), str(target), input_names=['audio'],
                          output_names=['features_v2', 'features_v1'],
                          dynamic_axes={'audio': {1: 'samples'}, 'features_v2': {1: 'frames'}, 'features_v1': {1: 'frames'}},
                          opset_version=17, dynamo=False)
    # The exported graph must agree with the PyTorch module on a length it was not traced with.
    import onnxruntime
    session = onnxruntime.InferenceSession(str(target), providers=['CPUExecutionProvider'])
    audio = np.random.default_rng(0).standard_normal((1, 23456)).astype(np.float32) * 0.1
    with torch.no_grad():
        expected = model(torch.from_numpy(audio))
    for found, wanted in zip(session.run(None, {'audio': audio}), expected):
        error = float(np.abs(found - wanted.numpy()).max())
        if found.shape != tuple(wanted.shape) or error > 1e-3:
            raise SystemExit(f'export check failed: shape {found.shape}, max error {error}')
    print(f'wrote {target} ({target.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
