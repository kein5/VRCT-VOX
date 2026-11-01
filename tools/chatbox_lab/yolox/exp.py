"""YOLOX-Tiny settings for the VRCT-VOX chatbox detector.

Starts from Megvii's COCO weights (yolox_tiny.pth, Apache-2.0), so the result
is licensed by us. Adapted from upstream VRCT's tools/yolox_chatbox_exp.py (MIT);
input size and augmentation follow its measurements.
"""
from pathlib import Path

from yolox.exp import Exp as BaseExp

DATASET = Path.home() / '.cache/vrct-vox-chatbox-lab/dataset'


class Exp(BaseExp):
    def __init__(self):
        super().__init__()
        self.depth = 0.33
        self.width = 0.375
        self.num_classes = 1
        self.exp_name = 'vrct_vox_chatbox_yolox_tiny'
        self.output_dir = str(Path.home() / '.cache/vrct-vox-chatbox-lab/train/runs')

        self.data_dir = str(DATASET)
        self.train_ann = 'instances_train.json'
        self.val_ann = 'instances_val.json'
        self.data_num_workers = 4

        # Chatboxes can be about 1% of the screen; 416 loses them.
        self.input_size = (1280, 1280)
        self.test_size = (1280, 1280)
        self.multiscale_range = 5

        self.mosaic_prob = 0.3
        self.enable_mixup = False
        self.mosaic_scale = (0.5, 1.5)
        self.translate = 0.05
        self.degrees = 0.0
        self.shear = 0.0
        self.flip_prob = 0.5
        self.hsv_prob = 1.0

        self.max_epoch = 80
        self.no_aug_epochs = 20
        self.warmup_epochs = 5
        self.eval_interval = 5
        self.seed = 0
        self.save_history_ckpt = False

        self.test_conf = 0.01
        self.nmsthre = 0.65

    def get_dataset(self, cache: bool = False, cache_type: str = 'ram'):
        from yolox.data import COCODataset, TrainTransform
        return COCODataset(data_dir=self.data_dir, json_file=self.train_ann, name='', img_size=self.input_size,
                           preproc=TrainTransform(max_labels=50, flip_prob=self.flip_prob, hsv_prob=self.hsv_prob),
                           cache=cache, cache_type=cache_type)

    def get_eval_dataset(self, **kwargs):
        from yolox.data import COCODataset, ValTransform
        return COCODataset(data_dir=self.data_dir, json_file=self.val_ann, name='', img_size=self.test_size,
                           preproc=ValTransform(legacy=kwargs.get('legacy', False)))
