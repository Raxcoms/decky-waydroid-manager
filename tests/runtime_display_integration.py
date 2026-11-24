"""Check normal and crash recovery on a systemd host with overlayfs."""

import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.runtime_display import RuntimeDisplayLease


def acquire(base):
    def run(command, *, timeout):
        if command[0] == "systemd-run":
            # Only guest discovery is simulated. The guard and mounts use the host kernel.
            command = [command[0], f"--setenv=PATH={base / 'test-bin'}:{os.defpath}", *command[1:]]
        return subprocess.check_output(command, stderr=subprocess.STDOUT, text=True, timeout=timeout)

    lease = RuntimeDisplayLease(base / "waydroid", base / "runtime")
    lease.acquire(
        {"vendor/test.so": base / "payload"}, Path("/run/user/1000/test-external"), run,
        base / "wayland",
    )
    return lease


if len(sys.argv) == 3 and sys.argv[1] == "--crash-child":
    lease = acquire(Path(sys.argv[2]))
    os._exit(0)

if os.geteuid() != 0:
    raise SystemExit("Run this integration test as root")

with tempfile.TemporaryDirectory(prefix="waydroid-display-integration-") as directory:
    base = Path(directory)
    tools = base / "test-bin"
    tools.mkdir()
    probe = tools / "lxc-info"
    probe.write_text("#!/bin/sh\nexit 1\n")
    probe.chmod(0o755)
    config = base / "waydroid"
    (config / "lxc/waydroid").mkdir(parents=True)
    (config / "overlay/vendor").mkdir(parents=True)
    (config / "overlay/vendor/existing").write_text("existing overlay")
    originals = {
        config / "lxc/waydroid/config": b"lxc.include = config_session\n",
        config / "waydroid.cfg": b"[waydroid]\n[properties]\n",
        config / "waydroid_base.prop": b"ro.hardware.gralloc=gbm\n",
    }
    for path, content in originals.items():
        path.write_bytes(content)
    (base / "payload").write_bytes(b"test payload")
    relay = socket.socket(socket.AF_UNIX)
    relay.bind(str(base / "wayland"))
    relay.close()
    lease = acquire(base)
    try:
        assert (config / "overlay/vendor/test.so").read_bytes() == b"test payload"
        assert b"wayland-1" in (config / "lxc/waydroid/config").read_bytes()
    finally:
        lease.recover()
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert not (config / "overlay/vendor/test.so").exists()
    subprocess.run([sys.executable, __file__, "--crash-child", str(base)], check=True)
    deadline = time.monotonic() + 15
    while lease.root.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not lease.root.exists(), "The independent guard did not clean up after backend exit"
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert not (config / "overlay/vendor/test.so").exists()
    assert (config / "overlay/vendor/existing").read_text() == "existing overlay"
print("Normal release and backend crash both restored original files and overlays")
