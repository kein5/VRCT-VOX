"""Process identity checks without importing a platform's audio/GUI harness."""
from pathlib import Path


def sidecars(ui):
    import psutil

    found = []
    for child in ui.app_process.children(recursive=True):
        try:
            if Path(child.exe()).name in ('main', 'vrct-vox-sidecar', 'vrct-vox-sidecar.bin'):
                found.append(child.pid)
        except psutil.NoSuchProcess:
            # Short-lived gate/playback helpers can exit during enumeration.
            continue
    return sorted(found)
