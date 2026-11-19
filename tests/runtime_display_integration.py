"""Run explicitly as root on a systemd host with overlayfs and LXC tools."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.runtime_display import RuntimeDisplayLease


def run(command, **kwargs):
    return subprocess.check_output(command, stderr=subprocess.STDOUT, text=True, timeout=30)


def acquire(base):
    RuntimeDisplayLease(base / "waydroid", base / "runtime").acquire(
        {"vendor/test.so": base / "payload"}, Path("/run/user/1000/test-external"), run,
        Path("/run/waydroid-manager-test-display"),
    )


if len(sys.argv) == 3 and sys.argv[1] == "--crash-child":
    acquire(Path(sys.argv[2]))
    os._exit(0)

if os.geteuid() != 0:
    raise SystemExit("Run this integration test as root")

with tempfile.TemporaryDirectory(prefix="waydroid-display-integration-") as directory:
    base = Path(directory)
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
    lease = RuntimeDisplayLease(config, base / "runtime")
    try:
        acquire(base)
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
