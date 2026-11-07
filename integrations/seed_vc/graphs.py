# SPDX-License-Identifier: GPL-3.0-only
"""CUDA graphs for the parts of a block whose shapes never change.

One block launches thousands of small kernels. On a laptop CPU, launching them took
far longer than the GPU took to run them. The pinned engine has no graphs of its own,
so this wraps its calls from outside. What a graph cannot hold stays eager: istft reads
a value back from the GPU, and the sine source builds its tensors on the CPU.
"""
import time
from types import SimpleNamespace

import torch

# (seconds of reference, diffusion steps), best first. The first is the normal profile.
LIGHTER = ((3.0, 10), (2.0, 10), (2.0, 8), (1.5, 6))
# Of the 80 ms, the worker's own resampling and pipes took about 7 ms on a laptop CPU.
BLOCK_BUDGET_MS = 68


class Replay:
    """Runs a function as one graph per input shape. Outputs are cloned for the caller."""
    def __init__(self, function):
        self.function = function
        self.entries = {}

    def _capture(self, inputs):
        static = tuple(value.clone() for value in inputs)
        side = torch.cuda.Stream()
        side.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(side):
            for _ in range(3):
                self.function(*static)
        torch.cuda.current_stream().wait_stream(side)
        torch.cuda.synchronize()
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph):
            output = self.function(*static)
        return SimpleNamespace(graph=graph, inputs=static, output=output)

    def __call__(self, *inputs):
        key = tuple((tuple(value.shape), value.dtype) for value in inputs)
        entry = self.entries.get(key)
        if entry is None:
            entry = self.entries[key] = self._capture(inputs)
        for static, value in zip(entry.inputs, inputs):
            static.copy_(value)
        entry.graph.replay()
        return entry.output.clone()


def graph_solver(cfm, module):
    """All diffusion steps as one graph.

    module: audio_modules.diffusion_transformer, whose sequence_mask reads length.max().
    x_lens is always the full length here, so every position is real and the mask needs
    only the shape. This is what keeps the value from being read back during capture.
    """
    estimator, solve = cfm.estimator, cfm.solve_euler
    forward = estimator.forward
    size = {}
    solvers = {}

    def mask(length):
        return torch.ones(length.shape[0], size['value'], dtype=torch.bool, device=length.device)

    def sized(x, *args, **kwargs):
        size['value'] = x.size(-1) + estimator.style_as_token + estimator.time_as_token
        return forward(x, *args, **kwargs)

    def replay(x, x_lens, prompt, mu, style, f0, t_span, inference_cfg_rate=.5):
        if inference_cfg_rate not in solvers:
            solvers[inference_cfg_rate] = Replay(lambda x, x_lens, prompt, mu, style, t_span: solve(
                x, x_lens, prompt, mu, style, None, t_span, inference_cfg_rate))
        return solvers[inference_cfg_rate](x, x_lens, prompt, mu, style, t_span)

    module.sequence_mask = mask
    estimator.forward = sized
    cfm.solve_euler = replay


class Vocoder:
    """HiFT's forward, with its middle in a graph. istft and the sine source stay eager."""
    def __init__(self, hift):
        self.hift = hift
        self.limit = hift.audio_limit
        self.forward = hift.forward
        self.istft = hift._istft
        hift.stft_window = hift.stft_window.to(next(hift.parameters()).device)
        self.predict = Replay(hift.f0_predictor)
        self.body = Replay(self._body)

    def _body(self, mel, source):
        # forward() runs unchanged. These hand it the source and take the spectrum it
        # would have inverted; they only exist while the graph is being recorded.
        hift = self.hift
        hift._f02source = lambda _: source
        hift._istft = lambda magnitude, phase: torch.stack((magnitude, phase))
        hift.audio_limit = float('inf')
        try:
            return self.forward(mel, f0=mel)
        finally:
            del hift._f02source
            hift._istft = self.istft
            hift.audio_limit = self.limit

    def __call__(self, mel):
        source = self.hift._f02source(self.predict(mel))
        magnitude, phase = self.body(mel, source)
        return torch.clamp(self.istft(magnitude, phase), -self.limit, self.limit)


def graph_semantic(xlsr):
    """The feature extractor's normalization, done here to spare a trip through the CPU."""
    def encode(waves):
        values = (waves - waves.mean()) / torch.sqrt(waves.var(unbiased=False) + 1e-7)
        return xlsr(values.half()).last_hidden_state.float()
    return Replay(encode)


def install(model, hift, module):
    """Weights must be cast inside each graph: autocast's cache would free them afterwards.

    A graph keeps the convolution it was recorded with, so searching for the fastest one
    costs nothing later: it took a block from 89 ms to 74 ms. The search borrows several
    GB once; release_search_memory gives it back.
    """
    torch.set_autocast_cache_enabled(False)
    torch.backends.cudnn.benchmark = True
    graph_solver(model.cfm, module)
    return Vocoder(hift)


def release_search_memory():
    torch.cuda.empty_cache()


def fit_block(engine, session, silence):
    """Settle on the first setting that leaves the worker time inside a block.

    A block that takes longer than 80 ms on average falls further behind with every
    word, so a slower GPU trades some likeness to the reference for keeping up. Silence
    costs the same as speech here: the model runs either way. Returns what was chosen.
    """
    for prompt, steps in LIGHTER:
        engine.config.max_prompt_length, engine.config.diffusion_steps = prompt, steps
        times = []
        for index in range(8):
            started = time.perf_counter()
            if session.convert(silence) is None:
                raise RuntimeError('vc_warmup_failed')
            if index >= 2:  # The first calls record the graphs for this shape.
                times.append((time.perf_counter() - started) * 1000)
        if sorted(times)[len(times) // 2] <= BLOCK_BUDGET_MS:
            break
    return prompt, steps
