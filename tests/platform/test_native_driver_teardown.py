"""Real disposable process trees; no desktop, driver or audio service required."""
import os
import signal
import subprocess
import sys
import time

import psutil
import pytest

from native_webdriver import NativeWebDriver


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Unix native-driver process ownership")


@pytest.mark.parametrize("resistant,detached", [(False, False), (True, False), (True, True)])
def test_teardown_stops_owned_child_even_when_driver_exits_first(tmp_path, resistant, detached):
    ready = tmp_path / "child.pid"
    child_code = (
        "import os,signal,sys,time; from pathlib import Path; "
        + ("signal.signal(signal.SIGTERM,signal.SIG_IGN); " if resistant else "")
        + "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],start_new_session={detached}); "
        "time.sleep(60)"
    )
    driver = NativeWebDriver(tmp_path / "ui")
    driver.log = (tmp_path / "driver.log").open("w")
    driver.process = subprocess.Popen(
        [sys.executable, "-c", parent_code, child_code, str(ready)], start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    child = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists(), "disposable child did not initialize"
        child = psutil.Process(int(ready.read_text()))
        driver.__exit__(None, None, None)
        assert driver.process.poll() is not None
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE, "owned child survived teardown"
    finally:
        # Also clean the intentional RED run; never leave a 60-second orphan.
        if child is not None:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            os.killpg(driver.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        driver.process.wait(timeout=3)
        driver.log.close()
