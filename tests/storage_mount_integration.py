"""Run as root in a private mount namespace with the compiled host helper."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


def run(*command):
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=10).strip()


def guest(root):
    ready, writer = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(ready)
        os.unshare(os.CLONE_NEWNS)
        os.chroot(root)
        os.chdir("/")
        os.write(writer, b"1")
        os.close(writer)
        while True:
            signal.pause()
    os.close(writer)
    try:
        if os.read(ready, 1) != b"1":
            raise RuntimeError("The test namespace did not start")
    finally:
        os.close(ready)
    return pid


if os.geteuid() != 0 or len(sys.argv) != 2:
    raise SystemExit("Run with sudo unshare --mount --propagation private python3 TEST HELPER")

helper = str(Path(sys.argv[1]).resolve(strict=True))
with tempfile.TemporaryDirectory(prefix="waydroid-storage-integration-") as directory:
    base = Path(directory)
    source = base / "source"
    source.mkdir()
    run("mount", "-t", "tmpfs", "tmpfs", str(source))
    pid = None
    try:
        run("mount", "--make-shared", str(source))
        view, home, root = source / "view", source / "home", base / "guest"
        (view / "Home").mkdir(parents=True)
        home.mkdir()
        (home / "sentinel").write_text("owned fixture")
        for path in (view, view / "Home", home, home / "sentinel"):
            os.chown(path, 1000, 1000)
        target = "/data/user/0/waydroid.manager.storage/files/Host"
        (root / target.lstrip("/")).parent.mkdir(parents=True)
        for attempt in range(2):
            pid = guest(root)
            namespace = str(Path(f"/proc/{pid}/ns/mnt").stat().st_ino)
            mounts = []
            for name, folder in (("", view), ("/Home", home)):
                identity = run(helper, "mount", str(pid), namespace, str(folder), target + name,
                               "1000", "2000", "1000", "2000").split()
                mounts.append((target + name, *identity))
            shared = Path(f"/proc/{pid}/root" + target) / "Home"
            assert (shared / "sentinel").read_text() == "owned fixture"
            assert shared.stat().st_uid == 2000
            assert not (view / "Home/sentinel").exists(), "A guest mount propagated into host staging"
            assert (view / "Home").stat().st_uid == 1000
            assert (home / "sentinel").stat().st_uid == 1000
            if attempt:
                for path, mount_id, created in reversed(mounts):
                    run(helper, "unmount", str(pid), namespace, path, mount_id, created)
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
            pid = None
            assert not (view / "Home/sentinel").exists()
    finally:
        if pid is not None:
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
        run("mount", "--make-rprivate", str(source))
        run("umount", "--recursive", str(source))

print("Private storage mounts preserve host ownership and survive provider namespace replacement")
