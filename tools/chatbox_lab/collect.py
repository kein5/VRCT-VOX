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
skipped, and the avatar worn at the start is restored at the end. Avatars
that an earlier online VRChat log reports as rejected or inaccessible are left
out up front: an avatar that fails VRChat's server-side checks is shown to
everyone as the error robot, so it adds nothing to the data.

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


REJECTED = re.compile(r"Avatar '(avtr_[0-9a-f-]+)' did not pass initial checks"
                      r"|inaccessible avatar: (avtr_[0-9a-f-]+)")


def rejected_avatars():
    """Avatars VRChat logs on this PC report as failing checks or inaccessible.

    Offline testing mode (the local test instance, or VRChat.exe started
    without Easy Anti-Cheat) cannot fetch other creators' avatars at all, so
    its logs do not count.
    """
    rejected = set()
    for log in VRCHAT_DATA.glob('output_log_*.txt'):
        text = log.read_text(errors='replace')
        if 'name=BuildAndRun' in text[:20000] or 'offline testing mode' in text:
            continue
        for match in REJECTED.finditer(text):
            rejected.add(match.group(1) or match.group(2))
    return rejected


def known_avatars():
    rejected = rejected_avatars()
    return sorted(avatar for avatar, name in avatar_names().items() if name and avatar not in rejected)


def client_log(profile: int) -> Path:
    """The newest VRChat log of the client started with --profile=<profile>."""
    logs = sorted(VRCHAT_DATA.glob('output_log_*.txt'), key=lambda p: p.stat().st_mtime, reverse=True)
    marker = f'Arg: --profile={profile}'
    return next(p for p in logs if marker in p.read_text(errors='replace')[:20000])


def read_from(path: Path, offset: int) -> str:
    with open(path, 'rb') as log:
        log.seek(offset)
        return log.read().decode('utf-8', errors='replace')


class AvatarSwitcher:
    """Switch the speaker's avatar and confirm it from the speaker's VRChat log.

    VRChat does not answer /avatar/change over OSC here, but its log says
    "Switching <user> to avatar <name>" when it switches (the name comes from
    the avatar's OSC config) and "did not pass initial checks" when it cannot
    be used. Switching changes the account's current avatar, so the one worn
    at the start is restored at the end.
    """

    def __init__(self, osc: SimpleUDPClient, profile: int = 0, camera_profile: int = 1):
        self.osc = osc
        self.log = client_log(profile)
        self.camera_log = client_log(camera_profile)
        names = avatar_names()
        text = self.log.read_text(errors='replace')
        # Other players' switches are logged the same way (online, the camera
        # account wears its own avatar), so look at the local player's only.
        local = re.search(r'Initialized PlayerAPI "(.+)" is local', text)
        player = re.escape(local.group(1)) if local else r'\S+'
        worn = re.findall(rf'Switching {player} to avatar (.+)', text)
        by_name = {name: avatar for avatar, name in names.items()}
        self.original = by_name.get(worn[-1].strip()) if worn else None
        self.names = names

    def switch(self, avatar_id: str, timeout: float = 30.0) -> bool:
        offset = self.log.stat().st_size
        camera_offset = self.camera_log.stat().st_size
        if not self._switched(avatar_id, offset, timeout):
            return False
        self._camera_loaded(avatar_id, camera_offset)
        return True

    def _camera_loaded(self, avatar_id: str, offset: int, timeout: float = 90.0) -> None:
        """Wait until the camera client shows the avatar, not the loading robot.

        An avatar it has to download is shown after "Unpacking Avatar (<name> by";
        a cached one is shown at once, without a download line.
        """
        name = self.names.get(avatar_id, '')
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            time.sleep(1.0)
            tail = read_from(self.camera_log, offset)
            if f'Unpacking Avatar ({name} by' in tail:
                return
            if 'Starting download of Avatar' not in tail and time.monotonic() - start >= 6.0:
                return

    def _switched(self, avatar_id: str, offset: int, timeout: float) -> bool:
        self.osc.send_message('/avatar/change', avatar_id)
        end = time.monotonic() + timeout
        switched_at = None
        while time.monotonic() < end:
            time.sleep(0.5)
            tail = read_from(self.log, offset)
            if f"'{avatar_id}' did not pass" in tail or f'inaccessible avatar: {avatar_id}' in tail:
                return False
            name = self.names.get(avatar_id)
            if switched_at is None and name and f'to avatar {name}' in tail:
                switched_at = time.monotonic()
            # A rejected avatar is reported right after the switch line.
            if switched_at is not None and time.monotonic() - switched_at >= 3.0:
                return True
        return False

    def restore(self) -> None:
        # Right after a switch VRChat may still be loading and ignore the change.
        if not self.original:
            return
        for _ in range(3):
            if self.switch(self.original):
                return
            time.sleep(10.0)
        print(f'could not switch back to {self.names.get(self.original, self.original)}; change it by hand', flush=True)


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
    if args.avatar_every:
        print(f'{len(avatars)} avatars to switch between', flush=True)
    switcher = AvatarSwitcher(osc, speaker['profile'], args.camera_profile) if avatars else None
    if switcher and args.restore_avatar:
        switcher.original = args.restore_avatar
    try:
        collect(args, osc, camera, out, rng, avatars, switcher)
    finally:
        osc.send_message('/chatbox/input', ['', True, False])
        if switcher:
            switcher.restore()


def change_avatar(switcher, avatars, rng, tries=20):
    """Switch to a random avatar that loads; drop the ones that do not.

    If none of the tries loads, go back to the avatar worn at the start rather
    than capture the error robot. Returns the avatar now worn, or None.
    """
    for candidate in rng.sample(avatars, min(tries, len(avatars))):
        if switcher.switch(candidate):
            return candidate
        avatars.remove(candidate)
        print(f'skipped {switcher.names.get(candidate, candidate)}: rejected by VRChat', flush=True)
    if switcher.original and switcher.switch(switcher.original):
        return switcher.original
    return None


def collect(args, osc, camera, out, rng, avatars, switcher):
    avatar = None
    end = time.monotonic() + args.minutes * 60
    count = 0
    with open(out / 'frames.jsonl', 'w', encoding='utf-8') as index:
        while time.monotonic() < end:
            if switcher and count % args.avatar_every == 0:
                avatar = change_avatar(switcher, avatars, rng)
            negative = args.negative_every and count % args.negative_every == args.negative_every - 1
            text = '' if negative else sample_text(rng)
            # (text, send immediately, no notification sound)
            osc.send_message('/chatbox/input', [text, True, False])
            time.sleep(1.2 if not negative else 2.0)
            frame = capture(camera)
            if frame is not None:
                name = f'{count:06d}.png'
                # The capture is BGR (OpenCV's order); PNG files are RGB.
                Image.fromarray(np.ascontiguousarray(frame[..., 2::-1])).save(out / name)
                index.write(json.dumps({'file': name, 'text': text, 'time': time.time(), 'avatar': avatar,
                                        'shape': list(frame.shape)}, ensure_ascii=False) + '\n')
                index.flush()
            count += 1
            time.sleep(max(0.0, args.interval - 1.2))
    print(f'{count} frames in {out}')


if __name__ == '__main__':
    sys.exit(main())
