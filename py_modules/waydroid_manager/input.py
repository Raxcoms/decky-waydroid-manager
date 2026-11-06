from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from .container import LXC_PATH, container_pid
from .proc import clean_env


STEAM_VENDOR = "28de"
STEAM_PRODUCT = "11ff"
ANDROID_INPUT_GID = 1004
STEAM_LAYOUT = f"Vendor_{STEAM_VENDOR}_Product_{STEAM_PRODUCT}.kl"


def attach(pid: int, *args: str) -> None:
    if container_pid() != pid:
        raise RuntimeError("The Waydroid container changed")
    result = subprocess.run(["lxc-attach", "-P", str(LXC_PATH), "-n", "waydroid", "--", *args],
                            env=clean_env(), capture_output=True, text=True, timeout=5, check=False)
    if result.returncode:
        raise RuntimeError(result.stdout.strip() or result.stderr.strip() or "Android input setup failed")


def steam_controllers() -> dict[str, int]:
    devices = {}
    for event in Path("/sys/class/input").glob("event*"):
        try:
            vendor = (event / "device/id/vendor").read_text().strip().lower()
            product = (event / "device/id/product").read_text().strip().lower()
            info = (Path("/dev/input") / event.name).stat()
            if (vendor, product) == (STEAM_VENDOR, STEAM_PRODUCT) and stat.S_ISCHR(info.st_mode):
                devices[event.name] = info.st_rdev
        except OSError:
            continue
    return devices


class RuntimeKeylayout:
    def __init__(self, pid: int, root: Path, run=attach):
        self.pid, self.root, self.run = pid, root, run
        self.directory = None
        self.mount_root = None

    def open(self) -> None:
        stock = self.root / "system/usr/keylayout"
        source = stock / "Vendor_045e_Product_028e.kl"
        content = source.read_bytes()
        legacy = self.root / "data/system/devices/keylayout"
        marker, target = legacy / ".waydroid-manager-steam-layout", legacy / STEAM_LAYOUT
        owned_legacy = marker.is_file() and target.is_file() and marker.read_text().strip() == source.name and target.read_bytes() == content
        if target.exists() and not owned_legacy:
            return
        if (stock / STEAM_LAYOUT).exists():
            if owned_legacy:
                target.unlink()
                marker.unlink()
            return
        self.directory = Path(tempfile.mkdtemp(prefix=".waydroid-manager-layout-", dir=self.root / "dev"))
        try:
            view = self.directory / "keylayout"
            shutil.copytree(stock, view, symlinks=True)
            view.chmod(0o755)
            (view / STEAM_LAYOUT).write_bytes(content)
            (view / STEAM_LAYOUT).chmod(0o644)
            source_path = f"/dev/{self.directory.name}/keylayout"
            self.run(self.pid, "/system/bin/mount", "--bind", source_path, "/system/usr/keylayout")
            self.mount_root = f"/{self.directory.name}/keylayout"
            # Remove only the matching file written by older plugin versions.
            if owned_legacy:
                target.unlink()
                marker.unlink()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if not self.directory:
            return
        if self.mount_root:
            try:
                mounts = (self.root.parent / "mountinfo").read_text().splitlines()
            except FileNotFoundError:
                return
            owned = any(len(parts := line.split()) > 5 and parts[3:5] == [self.mount_root, "/system/usr/keylayout"] for line in mounts)
            if owned:
                self.run(self.pid, "/system/bin/umount", "-l", "/system/usr/keylayout")
            self.mount_root = None
        shutil.rmtree(self.directory, ignore_errors=True)
        self.directory = None


@dataclass
class PublishedNode:
    device: int
    inode: int
    backup: Path | None


class InputNodes:
    def __init__(self, root: Path):
        self.inputs = root / "dev/input"
        host = Path("/dev/input")
        if host.exists():
            actual, source = self.inputs.stat(), host.stat()
            if (actual.st_dev, actual.st_ino) == (source.st_dev, source.st_ino):
                raise RuntimeError("Waydroid input directory is shared with the host")
        self.directory = Path(tempfile.mkdtemp(prefix=".waydroid-manager-input-", dir=root / "dev"))
        self.published: dict[str, PublishedNode] = {}

    def remove(self, name: str) -> None:
        node = self.published[name]
        target = self.inputs / name
        try:
            info = target.lstat()
        except FileNotFoundError:
            info = None
        if info is not None and (info.st_ino, info.st_rdev) != (node.inode, node.device):
            self.published.pop(name)
            return
        if info is not None:
            target.unlink()
        if node.backup and node.backup.exists():
            node.backup.rename(target)
        self.published.pop(name)

    def sync(self, controllers: dict[str, int]) -> None:
        for name in list(self.published):
            if controllers.get(name) != self.published[name].device:
                self.remove(name)
        for name, device in controllers.items():
            if name in self.published:
                continue
            target, backup = self.inputs / name, None
            if target.exists():
                if not stat.S_ISCHR(target.lstat().st_mode):
                    raise RuntimeError("Android input path is not an evdev node")
                backup = self.directory / name
                target.rename(backup)
            try:
                os.mknod(target, stat.S_IFCHR | 0o660, device)
                os.chown(target, 0, ANDROID_INPUT_GID)
                target.chmod(0o660)
            except Exception:
                target.unlink(missing_ok=True)
                if backup:
                    backup.rename(target)
                raise
            self.published[name] = PublishedNode(device, target.stat().st_ino, backup)

    def close(self) -> None:
        for name in list(self.published):
            self.remove(name)
        shutil.rmtree(self.directory, ignore_errors=True)
