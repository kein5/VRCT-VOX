"""Collect chatbox screenshots from the lab's camera client.

The speaker client gets chat text over OSC (/chatbox/input), and the camera
client's window is captured through X11/XWayland. Each frame is saved with the
text that was on screen, so labels can be made automatically later. Frames
with no chatbox are saved too, as negatives.

    python tools/chatbox_lab/collect.py --minutes 30 --avatar-every 12

With --avatar-every, the speaker switches to a random avatar from the ones
this account has worn (VRChat keeps an OSC config for each) every N
messages. VRChat only switches to avatars the account may use; the switch
is confirmed from the speaker's VRChat log, avatars that do not switch are
skipped, and the avatar worn at the start is restored at the end.

Run only in the lab's own local test instance: never capture other people.
"""
import argparse
import json
import random
import re
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
VRCHAT_DATA = (Path.home() / '.local/share/Steam/steamapps/compatdata/438100/pfx/drive_c/users/steamuser'
               / 'AppData/LocalLow/VRChat/VRChat')
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
        # The client also owns hidden helper windows; take its largest viewable one.
        best, best_area = None, 0
        for window in self._candidates():
            pid = self._pid(window)
            try:
                command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            except OSError:
                continue
            attributes = self._viewable(window)
            if f'--profile={self.profile}'.encode() in command and attributes is not None:
                area = attributes.width * attributes.height
                if area > best_area:
                    best, best_area = window, area
        return best


def avatar_names():
    """Avatars this PC's account has worn, by id: VRChat writes an OSC config for each."""
    names = {}
    for path in (VRCHAT_DATA / 'OSC').glob('usr_*/Avatars/avtr_*.json'):
        try:
            names[path.stem] = json.loads(path.read_text(encoding='utf-8-sig')).get('name') or ''
        except (OSError, ValueError):
            continue
    return names


def known_avatars():
    return sorted(avatar for avatar, name in avatar_names().items() if name)


class AvatarSwitcher:
    """Switch the speaker's avatar and confirm it from the speaker's VRChat log.

    VRChat does not answer /avatar/change over OSC here, but its log says
    "Switching <user> to avatar <name>" when it switches (the name comes from
    the avatar's OSC config) and "did not pass initial checks" when it cannot
    be used. Switching changes the account's current avatar, so the one worn
    at the start is restored at the end.
    """

    def __init__(self, osc: SimpleUDPClient, profile: int = 0):
        self.osc = osc
        logs = sorted(VRCHAT_DATA.glob('output_log_*.txt'), key=lambda p: p.stat().st_mtime, reverse=True)
        marker = f'Arg: --profile={profile}'
        self.log = next(p for p in logs if marker in p.read_text(errors='replace')[:20000])
        names = avatar_names()
        worn = re.findall(r'Switching \S+ to avatar (.+)', self.log.read_text(errors='replace'))
        by_name = {name: avatar for avatar, name in names.items()}
        self.original = by_name.get(worn[-1].strip()) if worn else None
        self.names = names

    def switch(self, avatar_id: str, timeout: float = 30.0) -> bool:
        offset = self.log.stat().st_size
        self.osc.send_message('/avatar/change', avatar_id)
        end = time.monotonic() + timeout
        switched_at = None
        while time.monotonic() < end:
            time.sleep(0.5)
            with open(self.log, encoding='utf-8', errors='replace') as log:
                log.seek(offset)
                tail = log.read()
            if f"'{avatar_id}' did not pass" in tail:
                return False
            name = self.names.get(avatar_id)
            if switched_at is None and name and f'to avatar {name}' in tail:
                switched_at = time.monotonic()
            # A rejected avatar is reported right after the switch line.
            if switched_at is not None and time.monotonic() - switched_at >= 3.0:
                return True
        return False

    def restore(self) -> None:
        if self.original:
            self.switch(self.original)


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
    parser.add_argument('--avatar-every', type=int, default=0, help='switch to a random avatar every N messages')
    parser.add_argument('--restore-avatar', default=None, help='avatar to wear afterwards (default: the one worn at start)')
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
    avatars = known_avatars() if args.avatar_every else []
    switcher = AvatarSwitcher(osc, speaker['profile']) if avatars else None
    if switcher and args.restore_avatar:
        switcher.original = args.restore_avatar
    try:
        collect(args, osc, camera, out, rng, avatars, switcher)
    finally:
        osc.send_message('/chatbox/input', ['', True, False])
        if switcher:
            switcher.restore()


def collect(args, osc, camera, out, rng, avatars, switcher):
    avatar = None
    end = time.monotonic() + args.minutes * 60
    count = 0
    with open(out / 'frames.jsonl', 'w', encoding='utf-8') as index:
        while time.monotonic() < end:
            if switcher and count % args.avatar_every == 0:
                for candidate in rng.sample(avatars, min(5, len(avatars))):
                    if switcher.switch(candidate):
                        avatar = candidate
                        time.sleep(4.0)  # let the avatar finish loading
                        break
            negative = args.negative_every and count % args.negative_every == args.negative_every - 1
            text = '' if negative else sample_text(rng)
            # (text, send immediately, no notification sound)
            osc.send_message('/chatbox/input', [text, True, False])
            time.sleep(1.2 if not negative else 2.0)
            frame = capture(camera)
            if frame is not None:
                name = f'{count:06d}.png'
                Image.fromarray(np.ascontiguousarray(frame[..., :3])).save(out / name)
                index.write(json.dumps({'file': name, 'text': text, 'time': time.time(), 'avatar': avatar,
                                        'shape': list(frame.shape)}, ensure_ascii=False) + '\n')
                index.flush()
            count += 1
            time.sleep(max(0.0, args.interval - 1.2))
    print(f'{count} frames in {out}')


if __name__ == '__main__':
    sys.exit(main())
