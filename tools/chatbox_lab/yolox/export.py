"""Export the trained detector to the ONNX layout BubbleDetector reads.

    .../venv/bin/python tools/chatbox_lab/yolox/export.py -o vrct_vox_chatbox_yolox_tiny.onnx

NMS stays out of the graph (YOLOX's uses torchvision.ops); BubbleDetector does
it in numpy. Adapted from upstream VRCT's tools/yolox_chatbox_export.py (MIT).
"""
import argparse
from pathlib import Path

import numpy as np
import torch
from torch import nn
from yolox.exp import get_exp
from yolox.models.network_blocks import SiLU
from yolox.utils import replace_module

HERE = Path(__file__).resolve().parent
RUN = Path.home() / '.cache/vrct-vox-chatbox-lab/train/runs/vrct_vox_chatbox_yolox_tiny'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--exp_file', default=str(HERE / 'exp.py'))
    parser.add_argument('-c', '--ckpt', default=str(RUN / 'best_ckpt.pth'))
    parser.add_argument('-o', '--output', default=str(RUN / 'vrct_vox_chatbox_yolox_tiny.onnx'))
    parser.add_argument('--opset', type=int, default=17)
    args = parser.parse_args()

    exp = get_exp(args.exp_file, None)
    model = exp.get_model()
    torch.serialization.add_safe_globals([np._core.multiarray.scalar, np.dtype, np.dtypes.Float64DType])
    checkpoint = torch.load(args.ckpt, map_location='cpu', weights_only=True)
    model.eval()
    model.load_state_dict(checkpoint.get('model', checkpoint))
    # onnxruntime-friendly SiLU, and decoded boxes in the output.
    model = replace_module(model, nn.SiLU, SiLU)
    model.head.decode_in_inference = True
    dummy = torch.randn(1, 3, *exp.test_size)
    # Variable height and width: captures are not square, and the padding can be trimmed.
    torch.onnx.export(model, dummy, args.output, input_names=['images'], output_names=['output'],
                      opset_version=args.opset, dynamic_axes={'images': {2: 'height', 3: 'width'}})
    print(f'wrote {args.output}')


if __name__ == '__main__':
    main()
