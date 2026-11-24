from contextlib import nullcontext
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid


class RuntimeDisplayLease:
    """Keep launch files in /run and mount them over the installed files."""

    def __init__(self, config_dir: Path, root: Path = Path("/run/waydroid-manager-display")):
        self.config_dir = config_dir
        self.root = root
        self.manifest = root / "mounts.json"
        self.owner = None

    @staticmethod
    def _unescape(value: str) -> str:
        return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)

    @classmethod
    def _mount_at(cls, target: Path) -> tuple[str | None, str]:
        # fdinfo names the visible mount even when several mounts share the path.
        fd = os.open(target, os.O_PATH | os.O_CLOEXEC)
        try:
            info = Path(f"/proc/self/fdinfo/{fd}").read_text()
            mount = re.search(r"^mnt_id:\s*(\d+)$", info, re.MULTILINE)
            if not mount:
                raise RuntimeError(f"Could not identify the current mount: {target}")
            for line in Path("/proc/self/mountinfo").read_text().splitlines():
                fields, _, filesystem = line.partition(" - ")
                parts = fields.split()
                if parts[0] == mount[1] and cls._unescape(parts[4]) == str(target):
                    return parts[0], filesystem
            return None, ""
        finally:
            os.close(fd)

    def _save(self, mounts: list[dict]) -> None:
        temporary = self.root / "mounts.new"
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(mounts, file)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(self.manifest)

    def _owns_mount(self, target: Path, index: int, filesystem: str) -> bool:
        if index:
            source = self.root / f"config-{index - 1}"
            expected, actual = source.stat(), target.stat()
            return (expected.st_dev, expected.st_ino) == (actual.st_dev, actual.st_ino)
        if not filesystem.startswith("overlay "):
            return False
        options = [self._unescape(value) for value in filesystem.split()[2].split(",")]
        return f"lowerdir={self.root / 'overlay'}:{target}" in options

    @staticmethod
    def _display_settings(source: Path, existing: Path) -> bytes:
        if not existing.exists():
            return source.read_bytes()
        if existing.is_symlink() or not existing.is_file() or existing.stat().st_size > 1024 * 1024:
            raise RuntimeError("Waydroid display settings are not a regular configuration file")
        from .proc import clean_env
        # Decky's bundled Python does not include ElementTree.
        return subprocess.check_output(["/usr/bin/python3", "-I", str(Path(__file__).with_name("display_settings.py")),
                                        str(existing)], env=clean_env(), timeout=5)

    def acquire(self, files: dict[str, Path], external: Path | None, run, display: Path,
                *, density_reference: tuple[int, int, int] | None = None) -> None:
        from .image_files import extract
        from .session_settings import session_configuration

        if self.root.exists():
            raise RuntimeError("An external display runtime is already active")
        self.root.mkdir(mode=0o700)
        overlay = self.root / "overlay"
        overlay.mkdir()
        try:
            if density_reference:
                from .density import CONFIG, prepare_density
                try:
                    prepare_density(self.config_dir, overlay, density_reference, run)
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                    (overlay / CONFIG).unlink(missing_ok=True)
                    logging.getLogger(__name__).warning("Automatic Android density unavailable: %s", error)
            for name, source in files.items():
                relative = Path(name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("Invalid external display overlay path")
                target = overlay / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if name == "vendor/etc/display_settings.xml":
                    existing = extract(self.config_dir, "vendor.img", ("/etc/display_settings.xml",),
                                       self.root / "display_settings.xml", run, missing_ok=True)
                    target.write_bytes(self._display_settings(source, existing))
                else:
                    shutil.copyfile(source, target)
                target.chmod(0o644)
            installed_overlay = self.config_dir / "overlay"
            if not installed_overlay.is_dir() or installed_overlay.is_symlink():
                raise RuntimeError("Waydroid's overlay directory is unavailable")
            contents = session_configuration(self.config_dir, external)
            for index, (target, content) in enumerate(contents.items()):
                if target.is_symlink() or not target.is_file():
                    raise RuntimeError(f"Waydroid configuration is not a regular file: {target}")
                staged = self.root / f"config-{index}"
                staged.write_bytes(content)
                staged.chmod(target.stat().st_mode & 0o777)
            # Record targets first so a guard can also undo interrupted startup.
            targets = [installed_overlay, *contents]
            mounts = [{"target": str(target), "previous": self._mount_at(target)[0]} for target in targets]
            self._save(mounts)
            self.start_guard(run, display)
            run(["mount", "-t", "overlay", "overlay", "-o",
                 f"ro,lowerdir={overlay}:{installed_overlay}", str(installed_overlay)], timeout=10)
            mounts[0]["applied"] = self._mount_at(installed_overlay)[0]
            self._save(mounts)
            for index, target in enumerate(contents):
                run(["mount", "--bind", str(self.root / f"config-{index}"), str(target)], timeout=10)
                mounts[index + 1]["applied"] = self._mount_at(target)[0]
                self._save(mounts)
        except Exception:
            self.recover()
            raise

    def start_guard(self, run, display: Path) -> None:
        import fcntl

        if not self.manifest.exists():
            self._save([])
        identity = uuid.uuid4().hex
        guard = self.root / f"guard-{identity}.py"
        shutil.copyfile(Path(__file__), guard)
        socket = display.stat()
        # Closing this descriptor wakes the guard on normal release or backend exit.
        self.owner = guard.open("rb")
        fcntl.flock(self.owner, fcntl.LOCK_EX)
        run(["systemd-run", "--quiet", "--collect", f"--unit=waydroid-manager-session-guard-{identity}",
             "--property=Restart=on-failure", "--property=RestartSec=1s", "--property=StartLimitIntervalSec=0",
             f"--property=ConditionPathExists={guard}", "/usr/bin/python3", "-I", str(guard),
             str(self.config_dir), str(socket.st_dev), str(socket.st_ino)], timeout=10)

    def _remove_staging(self) -> None:
        root = self.root.resolve()
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            target = Path(self._unescape(line.split()[4]))
            if target == root or root in target.parents:
                raise RuntimeError(f"Waydroid staging still contains a mount: {target}")
        shutil.rmtree(self.root)

    def recover(self, guard: Path | None = None, display_id: tuple[int, int] | None = None) -> None:
        import fcntl

        owner, self.owner = self.owner, None
        with owner or nullcontext():
            lock_path = self.root / "cleanup.lock"
            try:
                lock = lock_path.open("a")
            except FileNotFoundError:
                return
            with lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                # A concurrent cleanup can finish and a new lease can reuse the directory.
                if not lock_path.exists() or not os.path.samestat(lock_path.stat(), os.fstat(lock.fileno())):
                    return
                if guard is not None:
                    if not guard.exists():
                        return
                    stop_owned_guest(self.config_dir, display_id)
                if self.manifest.exists():
                    mounts = json.loads(self.manifest.read_text())
                    for index in reversed(range(len(mounts))):
                        mount = mounts[index]
                        target = Path(mount["target"])
                        current, filesystem = self._mount_at(target)
                        if current != mount["previous"]:
                            if (("applied" in mount and current != mount["applied"])
                                    or not self._owns_mount(target, index, filesystem)):
                                raise RuntimeError(f"Waydroid runtime mount changed: {target}")
                            subprocess.run(["umount", str(target)], check=True, timeout=10,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                self._remove_staging()


def stop_owned_guest(config: Path, display_id: tuple[int, int]) -> None:
    running = subprocess.run(["lxc-info", "-P", str(config / "lxc"), "-n", "waydroid", "-pH"],
                             capture_output=True, text=True, timeout=5)
    pid = running.stdout.strip()
    if running.returncode or not pid.isdecimal() or int(pid) <= 0:
        return
    try:
        socket = Path(f"/proc/{pid}/root/run/xdg/wayland-0").stat()
    except FileNotFoundError:
        return
    if (socket.st_dev, socket.st_ino) == display_id:
        subprocess.run(["busctl", "--system", "--timeout=20s", "call", "id.waydro.Container",
                        "/ContainerManager", "id.waydro.ContainerManager", "Stop", "b", "true"],
                       check=True, timeout=25)


def guard(script: Path, config: Path, display_id: tuple[int, int]) -> None:
    import fcntl

    try:
        lock = script.open("rb")
    except FileNotFoundError:
        return
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if script.exists():
            RuntimeDisplayLease(config, script.parent).recover(script, display_id)


if __name__ == "__main__":
    import sys
    guard(Path(__file__), Path(sys.argv[1]), (int(sys.argv[2]), int(sys.argv[3])))
