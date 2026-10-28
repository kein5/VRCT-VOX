# SPDX-License-Identifier: MIT
"""Fixed streaming profile adapted from pinned RVC realtime_gui.py.

SOLA algorithm credited upstream to yxlllc/DDSP-SVC. See LICENSE.upstream.
No audio device ownership, GUI, downloads or original-audio branch.
"""
import numpy as np
import torch
import torch.nn.functional as F
from torchaudio.transforms import Resample


class BlockSession:
    RATE, FRAMES, OVERLAP, SEARCH, HISTORY = 48000, 3840, 1920, 480, 96000

    def __init__(self, engine):
        if (engine.tgt_sr not in (32000, 40000, 48000) or engine.version not in ('v1', 'v2')
                or engine.if_f0 not in (0, 1)):
            raise ValueError('vc_engine_format_invalid')
        self.engine, self.device = engine, engine.device
        self.resample_in = Resample(self.RATE, 16000).to(self.device)
        self.resample_out = Resample(engine.tgt_sr, self.RATE).to(self.device)
        self.fade_in = torch.sin(torch.linspace(0, np.pi/2, self.OVERLAP, device=self.device))**2
        self.denominator = torch.ones(1, 1, self.OVERLAP, device=self.device)
        self.reset()

    def reset(self):
        size = self.HISTORY + self.OVERLAP + self.SEARCH + self.FRAMES
        self.input = torch.zeros(size, device=self.device)
        self.input16 = torch.zeros(size // 3, device=self.device)
        self.overlap = torch.zeros(self.OVERLAP, device=self.device)
        self.engine.cache_pitch.zero_()
        self.engine.cache_pitchf.zero_()

    @torch.no_grad()
    def convert(self, samples):
        if samples.shape != (self.FRAMES,) or not np.isfinite(samples).all():
            raise ValueError('vc_input_invalid')
        self.input[:-self.FRAMES] = self.input[self.FRAMES:].clone()
        self.input[-self.FRAMES:] = torch.as_tensor(samples, device=self.device)
        block16 = self.FRAMES // 3
        self.input16[:-block16] = self.input16[block16:].clone()
        # Keep 20 ms of preceding input for the resampler; discard its first 10 ms.
        self.input16[-block16-160:] = self.resample_in(self.input[-self.FRAMES-960:])[160:]
        output = self.engine.infer(self.input16, block16, 200, 13, 'rmvpe')
        if self.engine.index_rate:
            self.engine.index.require_success()
        expected = self.engine.tgt_sr * 13 // 100
        if (not torch.is_tensor(output) or output.shape != (expected,)
                or not torch.isfinite(output).all()):
            raise ValueError('vc_conversion_invalid')
        output = self.resample_out(output.float())
        if output.shape != (self.FRAMES + self.OVERLAP + self.SEARCH,):
            raise ValueError('vc_conversion_invalid')
        search = output[None, None, :self.OVERLAP+self.SEARCH]
        numerator = F.conv1d(search, self.overlap[None, None])
        denominator = torch.sqrt(F.conv1d(search**2, self.denominator) + 1e-8)
        offset = int(torch.argmax(numerator / denominator).item())
        aligned = output[offset:]
        aligned[:self.OVERLAP] = (aligned[:self.OVERLAP] * self.fade_in
                                 + self.overlap * (1-self.fade_in))
        self.overlap.copy_(aligned[self.FRAMES:self.FRAMES+self.OVERLAP])
        result = aligned[:self.FRAMES].cpu().numpy().copy()
        if not np.isfinite(result).all():
            raise ValueError('vc_conversion_invalid')
        return result
