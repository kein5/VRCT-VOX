"""Start the real SteamVR on its null driver, with settings and logs in a throwaway folder."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(os.environ.get('VOX_FIELD_ROOT') or Path(__file__).resolve().parents[2])
STEAMVR = Path(os.environ.get('VOX_STEAMVR') or r'C:\Program Files (x86)\Steam\steamapps\common\SteamVR')
BASE = ROOT / 'build/model-test/steamvr'
CONFIG, LOGS = BASE / 'config', BASE / 'logs'


def env():
    return {**os.environ, 'VR_CONFIG_PATH': str(CONFIG), 'VR_LOG_PATH': str(LOGS)}


def write_settings():
    CONFIG.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    settings = {
        'steamvr': {'requireHmd': False, 'forcedDriver': 'null', 'activateMultipleDrivers': True, 'enableHomeApp': False,
                    'showMirrorView': False, 'mirrorViewVisibility': False, 'startMonitorFromAppLaunch': True},
        'driver_null': {'enable': True, 'loadPriority': 999, 'windowWidth': 960, 'windowHeight': 540,
                        'renderWidth': 960, 'renderHeight': 540, 'displayFrequency': 60.0},
        'dashboard': {'enableDashboard': False},
    }
    (CONFIG / 'steamvr.vrsettings').write_text(json.dumps(settings, indent=2), encoding='utf-8')


def processes():
    out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True).stdout
    return sorted({line.split(',')[0].strip('"') for line in out.splitlines()
                   if line.lower().startswith('"vr') and '.exe' in line.lower()})


def start():
    write_settings()
    child = subprocess.Popen([str(STEAMVR / 'bin/win64/vrmonitor.exe')], env=env(), cwd=str(STEAMVR / 'bin/win64'))
    for _ in range(90):
        time.sleep(1)
        running = processes()
        if 'vrserver.exe' in running and 'vrmonitor.exe' in running:
            print('up after', _ + 1, 's', running, flush=True)
            return child
    print('not up', processes(), flush=True)
    return child


def stop():
    for name in ('vrmonitor.exe', 'vrcompositor.exe', 'vrserver.exe', 'vrwebhelper.exe', 'vrdashboard.exe', 'vrstartup.exe'):
        subprocess.run(['taskkill', '/F', '/IM', name], capture_output=True)
    time.sleep(1)
    print('left', processes(), flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'start':
        start()
    elif sys.argv[1] == 'stop':
        stop()
    else:
        print(processes())
