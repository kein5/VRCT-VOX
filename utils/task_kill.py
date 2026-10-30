import subprocess

# vrct-vox-sidecar.exe を強制終了
try:
    subprocess.run(
        ["taskkill", "/IM", "vrct-vox-sidecar.exe", "/F"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
except Exception:
    pass