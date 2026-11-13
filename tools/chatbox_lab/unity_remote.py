"""Run a chatbox lab action in the Unity editor that is already open.

    python tools/chatbox_lab/unity_remote.py build-scene
    python tools/chatbox_lab/unity_remote.py previews
    python tools/chatbox_lab/unity_remote.py build-world
    python tools/chatbox_lab/unity_remote.py upload
    python tools/chatbox_lab/unity_remote.py save-world-id

The editor polls ~/.cache/vrct-vox-chatbox-lab/remote through
unity/Editor/ChatboxLabRemote.cs, which knows only these actions and refresh.
Copy changed scripts into the project first; "refresh" makes the editor import
them. Upload needs the SDK panel signed in, and VRChat's copyright agreement
is answered in the editor by a person. Create the world the first time with
Build and Upload in the SDK panel, then run save-world-id.
"""
import argparse
import json
import sys
import time
from pathlib import Path

FOLDER = Path.home() / '.cache/vrct-vox-chatbox-lab/remote'
COMMANDS = ('refresh', 'build-scene', 'previews', 'build-world', 'upload', 'save-world-id')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=COMMANDS)
    parser.add_argument('--timeout', type=float, default=900.0)
    args = parser.parse_args()
    FOLDER.mkdir(parents=True, exist_ok=True)
    result = FOLDER / 'result.json'
    result.unlink(missing_ok=True)
    (FOLDER / 'command').write_text(args.command)
    end = time.monotonic() + args.timeout
    while time.monotonic() < end:
        if result.is_file():
            data = json.loads(result.read_text(encoding='utf-8'))
            print(data['message'])
            return 0 if data['ok'] else 1
        time.sleep(1.0)
    picked = not (FOLDER / 'command').exists()
    print('timed out: ' + ('the editor took the command but did not finish' if picked
                           else 'the editor did not pick up the command (is it open, compiled and idle?)'))
    return 2


if __name__ == '__main__':
    sys.exit(main())
