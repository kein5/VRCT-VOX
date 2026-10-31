"""Train the VRCT-VOX chatbox detector (YOLOX-Tiny) on one GPU.

    ~/.cache/vrct-vox-chatbox-lab/train/venv/bin/python tools/chatbox_lab/yolox/train.py

Needs the YOLOX 0.3.0 source on PYTHONPATH (train/yolox-src) and its COCO
weights (train/yolox_tiny.pth). Adapted from upstream VRCT's
tools/yolox_chatbox_train.py (MIT).
"""
import argparse
import random
import warnings
from pathlib import Path

import torch
from torch.backends import cudnn
from yolox.exp import check_exp_value, get_exp
from yolox.utils import configure_module, configure_omp

HERE = Path(__file__).resolve().parent
TRAIN = Path.home() / '.cache/vrct-vox-chatbox-lab/train'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--exp_file', default=str(HERE / 'exp.py'))
    parser.add_argument('-c', '--ckpt', default=str(TRAIN / 'yolox_tiny.pth'), help='COCO weights (Apache-2.0)')
    parser.add_argument('-b', '--batch-size', type=int, default=8)
    parser.add_argument('--fp16', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('opts', nargs=argparse.REMAINDER, default=None, help='exp overrides, e.g. max_epoch 40')
    args = parser.parse_args()
    # The attributes YOLOX's Trainer reads from tools/train.py's arguments.
    args.experiment_name, args.devices, args.start_epoch, args.occupy = None, 1, None, False
    args.cache, args.logger, args.num_machines, args.machine_rank = None, 'tensorboard', 1, 0
    args.dist_backend, args.dist_url, args.name = 'nccl', None, None

    configure_module()
    exp = get_exp(args.exp_file, None)
    exp.merge(args.opts)
    check_exp_value(exp)
    args.experiment_name = exp.exp_name
    if exp.seed is not None:
        random.seed(exp.seed)
        torch.manual_seed(exp.seed)
        cudnn.deterministic = True
        warnings.warn('seeded training enables cudnn.deterministic', stacklevel=1)
    configure_omp()
    cudnn.benchmark = True
    exp.get_trainer(args).train()


if __name__ == '__main__':
    main()
