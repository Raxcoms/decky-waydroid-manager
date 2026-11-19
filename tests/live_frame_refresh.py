"""Run inside an owned dual-display session with animated content on both outputs."""

from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.container import container_identity


def stress_refresh(run, cycles=10):
    guest = container_identity()
    if guest is None:
        raise RuntimeError("Start an owned dual-display session first")
    command = ["waydroid", "shell", "--"]
    previous = run([*command, "getprop", "waydroid.frame_limit"]).strip()
    applied = None
    first_counter = None
    try:
        for fps in [0, *([13, 37, 0] * cycles)]:
            if container_identity() != guest:
                raise RuntimeError("The test guest changed")
            applied = str(fps)
            run([*command, "setprop", "waydroid.frame_limit", applied])
            time.sleep(0.2)
            output = run([*command, "dumpsys", "SurfaceFlinger"], timeout=5)
            cadence = re.search(r"primary_period_ns=(\d+) primary_vsyncs=(\d+) external_period_ns=(\d+)", output)
            if cadence is None:
                raise RuntimeError("The composer did not report independent display cadence")
            if first_counter is None:
                first_counter = int(cadence[2])
        if int(cadence[2]) <= first_counter:
            raise RuntimeError("Primary presentation stopped during external mode refresh")
    finally:
        if container_identity() == guest and run([*command, "getprop", "waydroid.frame_limit"]).strip() == applied:
            run([*command, "setprop", "waydroid.frame_limit", previous or "0"])


if __name__ == "__main__":
    import subprocess
    def run(command, timeout=10):
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=timeout).strip()
    stress_refresh(run)
    print("Concurrent external refresh and presentation remained responsive")
