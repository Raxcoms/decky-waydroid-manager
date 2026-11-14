import json
import os
from pathlib import Path
import shutil
import subprocess
import time


class RuntimeDisplayLease:
    """Keep launch files in /run and mount them over the installed files."""

    def __init__(self, config_dir: Path, root: Path = Path("/run/waydroid-manager-display")):
        self.config_dir = config_dir
        self.root = root
        self.manifest = root / "mounts.json"

    @staticmethod
    def _mount_id(target: Path) -> str | None:
        result = None
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            fields = line.split()
            if fields[4] == str(target):
                result = fields[0]
        return result

    def _save(self, mounts: list[dict]) -> None:
        temporary = self.root / "mounts.new"
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(mounts, file)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(self.manifest)

    def acquire(self, files: dict[str, Path], external: Path, run, display: Path) -> None:
        from .session_config import SessionConfigLease

        if self.root.exists():
            raise RuntimeError("An external display runtime is already active")
        self.root.mkdir(mode=0o700)
        overlay = self.root / "overlay"
        overlay.mkdir()
        mounts = []
        try:
            for name, source in files.items():
                relative = Path(name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("Invalid external display overlay path")
                target = overlay / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                target.chmod(0o644)
            installed_overlay = self.config_dir / "overlay"
            if not installed_overlay.is_dir() or installed_overlay.is_symlink():
                raise RuntimeError("Waydroid's overlay directory is unavailable")
            configs = SessionConfigLease(self.config_dir)
            base = configs.base_properties.read_bytes()
            if b"waydroid.wayland_display_ext=" in base:
                raise RuntimeError("Waydroid's external display property is already configured")
            contents = {
                configs.config: configs.config.read_bytes().rstrip(b"\n") + b"\n"
                    + configs._fragment_config(external),
                configs.settings: configs._property_config(configs.settings.read_bytes()),
                configs.base_properties: base.rstrip(b"\n") + b"\nwaydroid.wayland_display_ext=wayland-1\n",
            }
            for index, (target, content) in enumerate(contents.items()):
                if target.is_symlink() or not target.is_file():
                    raise RuntimeError(f"Waydroid configuration is not a regular file: {target}")
                staged = self.root / f"config-{index}"
                staged.write_bytes(content)
                staged.chmod(target.stat().st_mode & 0o777)
            # Record targets first so a guard can also undo interrupted startup.
            targets = [installed_overlay, *contents]
            mounts = [{"target": str(target), "previous": self._mount_id(target)} for target in targets]
            self._save(mounts)
            guard = self.root / "guard.py"
            shutil.copyfile(Path(__file__), guard)
            backend = os.getpid()
            identity = Path(f"/proc/{backend}/stat").read_text().rsplit(")", 1)[1].split()[19]
            unit = f"waydroid-manager-display-guard-{backend}-{time.monotonic_ns()}"
            run(["systemd-run", "--quiet", "--collect", f"--unit={unit}",
                 "/usr/bin/python3", "-I", str(guard), str(self.config_dir), str(self.root),
                 str(backend), identity, str(display)], timeout=10)
            run(["mount", "-t", "overlay", "overlay", "-o",
                 f"ro,lowerdir={overlay}:{installed_overlay}", str(installed_overlay)], timeout=10)
            for index, target in enumerate(contents):
                run(["mount", "--bind", str(self.root / f"config-{index}"), str(target)], timeout=10)
        except Exception:
            self.recover()
            raise

    def recover(self) -> None:
        if not self.root.exists():
            return
        import fcntl

        with (self.root / "cleanup.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not self.manifest.exists():
                shutil.rmtree(self.root)
                return
            mounts = json.loads(self.manifest.read_text())
            for mount in reversed(mounts):
                target = Path(mount["target"])
                current = self._mount_id(target)
                if current != mount["previous"]:
                    subprocess.run(["umount", str(target)], check=True, timeout=10,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.manifest.unlink()
        shutil.rmtree(self.root)


def guard(config: Path, root: Path, backend: int, identity: str, display: str) -> None:
    while root.exists():
        try:
            fields = Path(f"/proc/{backend}/stat").read_text().rsplit(")", 1)[1].split()
            if fields[19] != identity or fields[0] == "Z":
                break
        except FileNotFoundError:
            break
        time.sleep(0.25)
    if not root.exists():
        return
    status = subprocess.run(["waydroid", "status"], capture_output=True, text=True, timeout=5)
    if any(line.partition(":")[2].strip() == display for line in status.stdout.splitlines()
           if line.startswith("Wayland display:")):
        subprocess.run(["busctl", "--system", "--timeout=20s", "call", "id.waydro.Container",
                        "/ContainerManager", "id.waydro.ContainerManager", "Stop", "b", "true"],
                       check=True, timeout=25)
    RuntimeDisplayLease(config, root).recover()


if __name__ == "__main__":
    import sys
    guard(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5])
