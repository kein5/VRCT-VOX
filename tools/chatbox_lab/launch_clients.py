"""Start VRChat test clients on the chatbox lab world through Proton.

The SDK's Build & Test cannot start the Windows client on Linux, so this does
what it does: one client per profile, desktop mode, its own OSC ports, all
joining a hidden local instance of the built world. The first client becomes
the instance master and speaks; the others are cameras.

    python tools/chatbox_lab/launch_clients.py --clients 2
    python tools/chatbox_lab/launch_clients.py --add --clients 1
    python tools/chatbox_lab/launch_clients.py --stop

VRChat uses the account already signed in on this PC. Close the clients from
their windows or with --stop.

    python tools/chatbox_lab/launch_clients.py --clients 2 --online

--online joins an invite-only instance of the uploaded private world on
VRChat's servers instead (world id from world-id, see unity_remote.py). There
each client needs its own account: sign the camera profile in to the lab's
second account once, and invite it from the speaker if VRChat does not let it
in by the link. Nobody else can join an invite-only instance.
"""
import argparse
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

APP_ID = '438100'
STEAM = Path.home() / '.local/share/Steam'
CACHE = Path.home() / '.cache/vrct-vox-chatbox-lab'
WORLD = CACHE / 'world.vrcw'
WORLD_ID = CACHE / 'world-id'
VRCHAT_DATA = (STEAM / 'steamapps/compatdata' / APP_ID / 'pfx/drive_c/users/steamuser/AppData/LocalLow/VRChat/VRChat')
STATE = CACHE / 'clients.json'


def steam_library_paths():
    paths = [STEAM]
    library = STEAM / 'steamapps/libraryfolders.vdf'
    if library.is_file():
        paths += [Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', library.read_text())]
    return paths


def find_vrchat():
    for root in steam_library_paths():
        install = root / 'steamapps/common/VRChat'
        if (install / 'VRChat.exe').is_file():
            return root, install
    raise SystemExit('VRChat is not installed through Steam')


def find_proton():
    """The compatibility tool Steam uses for VRChat."""
    config = (STEAM / 'config/config.vdf').read_text(errors='replace')
    match = re.search(r'"CompatToolMapping".*?"' + APP_ID + r'"\s*\{\s*"name"\s+"([^"]+)"', config, re.DOTALL)
    name = match.group(1) if match else 'proton_experimental'
    candidates = [Path.home() / '.steam/root/compatibilitytools.d' / name, STEAM / 'compatibilitytools.d' / name]
    for root in steam_library_paths():
        common = root / 'steamapps/common'
        if common.is_dir():
            candidates += [p for p in common.iterdir() if p.name.lower().replace(' ', '_').startswith(name.lower())]
    for candidate in candidates:
        if (candidate / 'proton').is_file():
            return candidate / 'proton'
    raise SystemExit(f'Proton tool "{name}" not found')


def world_url(world: Path, room: str) -> str:
    # Proton maps the Linux root to drive Z:.
    return f'create?roomId={room}&hidden=true&name=BuildAndRun&url=file:///Z:{world.as_posix()}'


def speaker_account():
    """The user id the speaker profile (0) last signed in with, from its VRChat log."""
    logs = sorted(VRCHAT_DATA.glob('output_log_*.txt'), key=lambda p: p.stat().st_mtime, reverse=True)
    for log in logs:
        text = log.read_text(errors='replace')
        if 'Arg: --profile=0' not in text[:20000]:
            continue
        local = re.search(r'Initialized PlayerAPI "(.+)" is local', text)
        if local:
            user = re.search(re.escape(local.group(1)) + r' \((usr_[0-9a-f-]{36})\)', text)
            if user:
                return user.group(1)
    raise SystemExit('Start the speaker once (any world) so its account can be read from the log, or pass --owner')


def online_url(world_id: str, owner: str, room: str) -> str:
    # Invite-only: only the owner and the people it invites can join.
    return f'vrchat://launch?ref=vrchat.com&id={world_id}:{room}~private({owner})~region(jp)'


def launch(args):
    if args.online:
        if not WORLD_ID.is_file():
            raise SystemExit(f'{WORLD_ID} is missing; upload the world and run unity_remote.py save-world-id')
        world_id, owner = WORLD_ID.read_text().strip(), args.owner or speaker_account()
    elif not args.world.is_file():
        raise SystemExit(f'{args.world} is missing; build it in Unity with VRCT-VOX > Build Chatbox Lab World')
    library, install = find_vrchat()
    proton = find_proton()
    env = dict(os.environ, SteamAppId=APP_ID, SteamGameId=APP_ID,
               STEAM_COMPAT_DATA_PATH=str(library / 'steamapps/compatdata' / APP_ID),
               STEAM_COMPAT_CLIENT_INSTALL_PATH=str(STEAM))
    # --add joins more clients to the running instance; it needs the same room.
    state = json.loads(STATE.read_text()) if args.add and STATE.is_file() else {'clients': []}
    room = state.get('room') or str(random.randint(10_000, 99_999) if args.online else random.randint(10_000_000, 99_999_999))
    clients = state['clients']
    first = len(clients)
    CACHE.mkdir(parents=True, exist_ok=True)
    for index in range(first, first + args.clients):
        osc_in, osc_out = args.osc_base + 2 * index, args.osc_base + 2 * index + 1
        url = online_url(world_id, owner, room) if args.online else f'--url={world_url(args.world, room)}'
        command = [str(proton), 'run', str(install / args.exe), '--no-vr', f'--profile={index}',
                   f'--osc={osc_in}:127.0.0.1:{osc_out}', url]
        if not args.online:
            command += ['--enable-sdk-log-levels', '--enable-udon-debug-logging']
        # The client keeps writing after this script exits.
        with open(CACHE / f'client{index}.log', 'w') as log:
            process = subprocess.Popen(command, cwd=install, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        clients.append({'profile': index, 'role': 'speaker' if index == 0 else 'camera', 'pid': process.pid,
                        'osc_in': osc_in, 'osc_out': osc_out})
        print(f'client {index} ({clients[-1]["role"]}): pid {process.pid}, OSC in {osc_in}, out {osc_out}')
        # The speaker must be master, so it has to join first.
        if index == 0 and first + args.clients > 1:
            time.sleep(args.stagger)
    STATE.write_text(json.dumps({'room': room, 'online': args.online, 'clients': clients}, indent=2))
    if args.online:
        print(f'instance: {online_url(world_id, owner, room)}')


def stop(_args):
    if not STATE.is_file():
        return
    # Wine reparents VRChat.exe away from the launcher, so find the clients by
    # their profile argument as well as by the launcher's process group.
    profiles = {f'--profile={c["profile"]}' for c in json.loads(STATE.read_text())['clients']}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / 'cmdline').read_bytes().decode(errors='replace').split('\0')
        except OSError:
            continue
        if any(a.lower().endswith('vrchat.exe') for a in argv) and profiles & set(argv):
            try:
                os.kill(int(proc.name), signal.SIGTERM)
            except ProcessLookupError:
                pass
    for client in json.loads(STATE.read_text())['clients']:
        try:
            os.killpg(client['pid'], signal.SIGTERM)
        except ProcessLookupError:
            pass
    STATE.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--clients', type=int, default=2)
    parser.add_argument('--world', type=Path, default=WORLD)
    parser.add_argument('--exe', default=None,
                        help='default: VRChat.exe, or start_protected_game.exe (Easy Anti-Cheat) with --online, as Steam '
                             'starts it; VRChat.exe alone runs in offline testing mode and cannot join online worlds')
    parser.add_argument('--osc-base', type=int, default=9100)
    parser.add_argument('--stagger', type=float, default=60.0, help='seconds before starting the camera clients')
    parser.add_argument('--add', action='store_true', help='add clients to the running instance')
    parser.add_argument('--online', action='store_true', help="invite-only instance of the uploaded world on VRChat's servers")
    parser.add_argument('--owner', help='user id that owns the instance (default: the speaker profile\'s account)')
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    args.exe = args.exe or ('start_protected_game.exe' if args.online else 'VRChat.exe')
    (stop if args.stop else launch)(args)


if __name__ == '__main__':
    sys.exit(main())
