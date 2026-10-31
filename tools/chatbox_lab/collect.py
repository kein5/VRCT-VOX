"""Collect chatbox screenshots from the lab's camera client.

The speaker client gets chat text over OSC (/chatbox/input), and the camera
client's window is captured through X11/XWayland. Each frame is saved with the
text that was on screen, so labels can be made automatically later. Frames
with no chatbox are saved too, as negatives.

    python tools/chatbox_lab/collect.py --minutes 30

Run only in the lab's own local test instance: never capture other people.
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from pythonosc.udp_client import SimpleUDPClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src-python'))
from models.ocr.ocr_capture_x11 import X11WindowCapture

CACHE = Path.home() / '.cache/vrct-vox-chatbox-lab'
CHATBOX_LIMIT = 144

PHRASES = [
    'こんばんは！', 'よろしくお願いします', 'いまどこのワールドにいますか？', 'フレンド申請してもいい？', '集会は21時からです',
    'ミラーの前で写真撮ろう', 'アバターかわいいですね', 'ちょっと離席します', 'おかえりなさい', '音声聞こえてますか？',
    'Hello!', 'Nice to meet you', 'Where are you from?', 'Can you hear me?', 'brb', 'Let me send you a friend request',
    'This world is beautiful', 'See you at the event tonight', 'Thank you so much!', 'gg', 'lol',
    '你好', '谢谢你', '我来自台湾', '안녕하세요', '반갑습니다', 'Привет', 'Bonjour à tous', '¡Hola!',
    'VRChat', 'Quest対応してますか？', 'BOOTHで買いました', 'フルトラ楽しい', '21:30', '12345', 'w', '草',
]


def sample_text(rng: random.Random) -> str:
    parts = rng.sample(PHRASES, rng.choice((1, 1, 1, 2, 3, 5)))
    text = rng.choice((' ', '\n', ' ')).join(parts)
    return text[:CHATBOX_LIMIT]


class CameraWindow(X11WindowCapture):
    """The camera client's window, told apart from the speaker's by its profile."""

    def __init__(self, profile: int):
        super().__init__()
        self.profile = profile

    def findWindow(self):
        if self._open() is None:
            return None
        self._begin()
        for window in self._candidates():
            pid = self._pid(window)
            try:
                command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            except OSError:
                continue
            if f'--profile={self.profile}'.encode() in command:
                return window
        return None


def capture(camera: CameraWindow, retries: int = 5):
    for _ in range(retries):
        frame = camera.capture()
        if frame is not None and frame.size and frame.max() > 8:
            return frame
        time.sleep(0.2)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--minutes', type=float, default=10.0)
    parser.add_argument('--camera-profile', type=int, default=1)
    parser.add_argument('--interval', type=float, default=2.5, help='seconds between chat messages (OSC is rate limited)')
    parser.add_argument('--negative-every', type=int, default=5, help='capture a frame without chatbox every N messages')
    parser.add_argument('--seed', type=int, default=None)
    args = parser.parse_args()

    state = json.loads((CACHE / 'clients.json').read_text())
    speaker = next(c for c in state['clients'] if c['role'] == 'speaker')
    osc = SimpleUDPClient('127.0.0.1', speaker['osc_in'])
    camera = CameraWindow(args.camera_profile)
    if camera.findWindow() is None:
        raise SystemExit(f'camera window for profile {args.camera_profile} not found')

    session = time.strftime('%Y%m%d-%H%M%S')
    out = CACHE / 'dataset/raw' / session
    out.mkdir(parents=True)
    rng = random.Random(args.seed)
    end = time.monotonic() + args.minutes * 60
    count = 0
    with open(out / 'frames.jsonl', 'w', encoding='utf-8') as index:
        while time.monotonic() < end:
            negative = args.negative_every and count % args.negative_every == args.negative_every - 1
            text = '' if negative else sample_text(rng)
            # (text, send immediately, no notification sound)
            osc.send_message('/chatbox/input', [text, True, False])
            time.sleep(1.2 if not negative else 2.0)
            frame = capture(camera)
            if frame is not None:
                name = f'{count:06d}.png'
                Image.fromarray(np.ascontiguousarray(frame[..., :3])).save(out / name)
                index.write(json.dumps({'file': name, 'text': text, 'time': time.time(),
                                        'shape': list(frame.shape)}, ensure_ascii=False) + '\n')
                index.flush()
            count += 1
            time.sleep(max(0.0, args.interval - 1.2))
    osc.send_message('/chatbox/input', ['', True, False])
    print(f'{count} frames in {out}')


if __name__ == '__main__':
    sys.exit(main())
