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


@dataclass(frozen=True)
class ControllerDevice:
    number: int
    identity: str


def controller_sources() -> tuple[dict[str, ControllerDevice], dict[str, ControllerDevice]]:
    steam, shared = {}, {}
    for event in Path("/sys/class/input").glob("event*"):
        try:
            vendor = (event / "device/id/vendor").read_text().strip().lower()
            product = (event / "device/id/product").read_text().strip().lower()
            info = (Path("/dev/input") / event.name).stat()
            if not stat.S_ISCHR(info.st_mode):
                continue
            device = ControllerDevice(info.st_rdev, str(event.resolve()))
            if (vendor, product) == (STEAM_VENDOR, STEAM_PRODUCT):
                steam[event.name] = device
            elif stat.S_IMODE(info.st_mode) == 0:
                database = Path(f"/run/udev/data/c{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}")
                if "E:INPUTPLUMBER_SHARED_GAMEPAD=1" in database.read_text().splitlines():
                    shared[event.name] = device
        except OSError:
            continue
    return steam, shared


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
    source: ControllerDevice
    inode: int


class InputNodes:
    def __init__(self, root: Path):
        self.inputs = root / "dev/input"
        host = Path("/dev/input")
        if host.exists():
            actual, source = self.inputs.stat(), host.stat()
            if (actual.st_dev, actual.st_ino) == (source.st_dev, source.st_ino):
                raise RuntimeError("Waydroid input directory is shared with the host")
        self.directory = Path(tempfile.mkdtemp(prefix=".waydroid-manager-input-", dir=self.inputs))
        self.published: dict[str, PublishedNode] = {}
        self.masked: dict[str, ControllerDevice] = {}

    def _alias(self, name: str) -> Path:
        # Keep the plugin node distinct from nodes reconciled by the platform.
        return self.inputs / f"waydroid-manager-{name}"

    @staticmethod
    def _matches(path: Path, device: ControllerDevice, inode: int | None = None) -> bool:
        try:
            info = path.lstat()
            return stat.S_ISCHR(info.st_mode) and info.st_rdev == device.number and (inode is None or info.st_ino == inode)
        except FileNotFoundError:
            return False

    def remove(self, name: str) -> None:
        node = self.published[name]
        target = self._alias(name)
        if self._matches(target, node.source, node.inode):
            target.unlink(missing_ok=True)
        self.published.pop(name)

    def _restore_shared(self, name: str, device: ControllerDevice | None) -> None:
        backup = self.directory / name
        if device == self.masked[name] and backup.exists():
            try:
                os.link(backup, self.inputs / name)
            except FileExistsError:
                pass
        backup.unlink(missing_ok=True)
        self.masked.pop(name)

    def sync(self, controllers: dict[str, ControllerDevice], shared: dict[str, ControllerDevice] | None = None) -> None:
        shared = shared or {}
        exposed = {name: source for name, source in shared.items()
                   if self.masked.get(name) == source or self._matches(self.inputs / name, source)}
        # With an ambiguous mapping, keep the platform's existing controller path.
        if exposed and (len(exposed) != 1 or len(controllers) != 1):
            controllers = {}
        for name, node in list(self.published.items()):
            # A new input device can reuse the previous evdev number.
            if (controllers.get(name) != node.source or not self._matches(self._alias(name), node.source, node.inode)
                    or self._matches(self.inputs / name, node.source)):
                self.remove(name)
        for name, device in controllers.items():
            if name in self.published or self._matches(self.inputs / name, device):
                continue
            target = self._alias(name)
            staged = self.directory / f".{name}"
            try:
                os.mknod(staged, stat.S_IFCHR | 0o660, device.number)
                os.chown(staged, 0, ANDROID_INPUT_GID)
                staged.chmod(0o660)
                inode = staged.stat().st_ino
                # Publish only after permissions are ready for Android's create notification.
                os.link(staged, target)
                self.published[name] = PublishedNode(device, inode)
            finally:
                staged.unlink(missing_ok=True)
        for name, device in list(self.masked.items()):
            if not controllers or exposed.get(name) != device:
                self._restore_shared(name, shared.get(name))
        if controllers:
            for name, device in exposed.items():
                source, backup = self.inputs / name, self.directory / name
                if not self._matches(source, device):
                    continue
                # Hide only the delegated copy inside Android, so input is not delivered twice.
                backup.unlink(missing_ok=True)
                os.link(source, backup)
                self.masked[name] = device
                source.unlink(missing_ok=True)

    def close(self, shared: dict[str, ControllerDevice] | None = None) -> None:
        for name in list(self.published):
            self.remove(name)
        for name in list(self.masked):
            self._restore_shared(name, (shared or {}).get(name))
        shutil.rmtree(self.directory, ignore_errors=True)
