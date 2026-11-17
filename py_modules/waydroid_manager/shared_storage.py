"""Own Android's Host folder and its home and external-volume mounts."""

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess

from .container import container_identity
from .display_payload import digest, elf_machine
from .guest import run_dex
from .host_storage import folder_name, mounted_volumes
from .proc import process_identity
from .runtime_display import RuntimeDisplayLease


class SharedStorage:
    def __init__(self, config: Path, plugin: Path, root: Path = Path("/run/waydroid-manager-storage")):
        self.plugin, self.root = plugin, root
        self.guard = RuntimeDisplayLease(config, root)
        self.guest: tuple[int, str] | None = None
        self.mounts: dict[str, tuple] = {}
        self.volumes = {}
        self.home = None
        self.ready = False
        self.process = None

    def _helper(self) -> Path:
        machine = elf_machine(Path("/usr/bin/python3").resolve())
        bundle = self.plugin / "bin/display-tools" / str(machine)
        helper = bundle / "home-mount"
        metadata = json.loads((bundle / "manifest.json").read_text())
        if (helper.is_symlink() or metadata.get("elfMachine") != machine
                or digest(helper) != metadata.get("files", {}).get("home-mount") or elf_machine(helper) != machine):
            raise RuntimeError("The host storage mount helper failed validation")
        return helper

    def _mount(self, name: str, source: Path, run) -> None:
        if container_identity() != self.guest or process_identity(self.process[0]) != self.process:
            raise RuntimeError("Android restarted while preparing host storage")
        target = self.target if not name else f"{self.target}/{name}"
        output = run([str(self.root / "home-mount"), "mount", str(self.process[0]), str(self.namespace),
                      str(source), target, str(self.uid), self.android_uid, str(self.gid), self.android_gid], timeout=10).split()
        if len(output) != 2 or not all(value.isdecimal() for value in output):
            raise RuntimeError("The storage mount helper returned an invalid mount identity")
        self.mounts[name] = self.namespace, target, *output

    def _unmount(self, name: str, run) -> None:
        namespace, target, mount_id, created = self.mounts[name]
        run([str(self.root / "home-mount"), "unmount", str(self.process[0]), str(namespace),
             target, mount_id, created], timeout=10)
        del self.mounts[name]

    def _folder(self, name: str) -> None:
        path = self.root / "view" / name
        path.mkdir(mode=0o555, exist_ok=True)
        os.chown(path, self.uid, self.gid)

    @staticmethod
    def _mapped_id(guest: int, filename: str, value: int) -> int:
        for line in Path(f"/proc/{guest}/{filename}").read_text().splitlines():
            inside, outside, count = map(int, line.split())
            if inside <= value < inside + count:
                return outside + value - inside
        raise RuntimeError("Android's storage identity is not mapped to the host")

    def _connect_provider(self, run) -> None:
        output = run_dex(run, self.plugin / "bin/waydroid-verifier.dex", container_identity, self.guest,
                         "waydroid.manager.StorageIdentity", self.user)
        values = dict(re.findall(r"^STORAGE_(UID|PID|PATH):([^\r\n]+)$", output, re.MULTILINE))
        if not values.get("UID", "").isdecimal() or not values.get("PID", "").isdecimal() or "PATH" not in values:
            raise RuntimeError("Android did not identify the Host storage provider")
        uid = self._mapped_id(self.guest[0], "uid_map", int(values["UID"]))
        gid = self._mapped_id(self.guest[0], "gid_map", int(values["UID"]))
        namespace = Path(f"/proc/{self.guest[0]}/ns/pid").stat().st_ino
        provider = None
        for path in Path("/proc").glob("[0-9]*"):
            try:
                if path.stat().st_uid != uid or (path / "ns/pid").stat().st_ino != namespace:
                    continue
                status = (path / "status").read_text()
                pid = re.search(r"^NSpid:\s+([\d\s]+)$", status, re.MULTILINE)
                if pid and pid[1].split()[-1] == values["PID"]:
                    provider = process_identity(int(path.name))
                    break
            except OSError:
                continue
        if provider is None:
            raise RuntimeError("The Host storage provider stopped during setup")
        self.process = provider
        self.namespace = Path(f"/proc/{provider[0]}/ns/mnt").stat().st_ino
        self.target = values["PATH"]
        self.android_uid, self.android_gid = str(uid), str(gid)

    def _initialize_mounts(self, run) -> None:
        self._connect_provider(run)
        self.mounts.clear()
        self.volumes.clear()
        self._mount("", self.root / "view", run)
        self._folder("Home")
        self._mount("Home", self.home, run)

    @staticmethod
    def _notify(run) -> None:
        run(["waydroid", "shell", "--", "content", "query", "--uri",
             "content://waydroid.manager.storage.documents/document/__refresh", "--projection", "document_id"], timeout=5)

    def ensure(self, home: Path, uid: int, display: Path, run) -> None:
        guest = container_identity()
        if not guest:
            raise RuntimeError("WAYDROID_NOT_RUNNING")
        if self.guest == guest:
            if not self.ready:
                raise RuntimeError("Host storage setup did not finish. Close the running Waydroid shortcuts before retrying")
            return
        if self.root.exists():
            raise RuntimeError("The previous host storage session is still closing")
        home = home.resolve(strict=True)
        owner = home.stat()
        if owner.st_uid != uid:
            raise RuntimeError("The home folder is not owned by the Steam login user")
        user = run(["waydroid", "shell", "--", "cmd", "activity", "get-current-user"], timeout=5).strip()
        if not user.isascii() or not user.isdecimal():
            raise RuntimeError("Could not identify the current Android user")
        helper = self._helper()
        self.user = user
        self.uid, self.gid = uid, owner.st_gid
        self.root.mkdir(mode=0o700)
        try:
            staged = self.root / "home-mount"
            shutil.copyfile(helper, staged)
            staged.chmod(0o700)
            view = self.root / "view"
            view.mkdir(mode=0o555)
            os.chown(view, self.uid, self.gid)
            self.guard.start_guard(run, display)
            self.guest = guest
            self.home = home
            self._initialize_mounts(run)
            self.ready = True
            self.refresh(run)
        except Exception:
            if self.guest is None:
                self.guard.recover()
            raise

    def refresh(self, run) -> None:
        if not self.ready or container_identity() != self.guest:
            return
        if self.process is None or process_identity(self.process[0]) != self.process:
            self._initialize_mounts(run)
        try:
            volumes = {volume.identity: volume for volume in mounted_volumes(run)}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            logging.getLogger(__name__).warning("External storage discovery unavailable: %s", error)
            self._notify(run)
            return
        for identity, (previous, name) in list(self.volumes.items()):
            if volumes.get(identity) != previous:
                self._unmount(name, run)
                (self.root / "view" / name).rmdir()
                del self.volumes[identity]
        used = {name.casefold() for name in self.mounts}
        for identity, volume in volumes.items():
            if identity in self.volumes or volume.path == self.home:
                continue
            name = folder_name(volume.label)
            base = name
            suffix = hashlib.sha256(identity.encode()).hexdigest()[:8]
            number = 0
            while name.casefold() in used:
                number += 1
                extra = suffix if number == 1 else f"{suffix}-{number}"
                name = f"{base} ({extra})"
            self._folder(name)
            try:
                self._mount(name, volume.path, run)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                (self.root / "view" / name).rmdir()
                logging.getLogger(__name__).warning("Could not share external storage %s: %s", volume.label, error)
                continue
            self.volumes[identity] = volume, name
            used.add(name.casefold())
        self._notify(run)

    def release(self, run) -> None:
        if self.guest is not None and container_identity() == self.guest and self.process is not None and process_identity(self.process[0]) == self.process:
            for name in reversed(tuple(self.mounts)):
                self._unmount(name, run)
        self.recover()

    def recover(self) -> None:
        self.guard.recover()
        self.guest = None
        self.ready = False
        self.process = None
        self.mounts.clear()
        self.volumes.clear()
