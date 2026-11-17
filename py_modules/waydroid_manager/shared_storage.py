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
        if container_identity() != self.guest:
            raise RuntimeError("Android restarted while preparing host storage")
        target = self.target if not name else f"{self.target}/{name}"
        output = run([str(self.root / "home-mount"), "mount", str(self.guest[0]), str(self.namespace),
                      str(source), target, str(self.uid), self.android_uid, str(self.gid), self.android_gid], timeout=10).split()
        if len(output) != 2 or not all(value.isdecimal() for value in output):
            raise RuntimeError("The storage mount helper returned an invalid mount identity")
        self.mounts[name] = self.namespace, target, *output

    def _unmount(self, name: str, run) -> None:
        namespace, target, mount_id, created = self.mounts[name]
        run([str(self.root / "home-mount"), "unmount", str(self.guest[0]), str(namespace),
             target, mount_id, created], timeout=10)
        del self.mounts[name]

    def _folder(self, name: str) -> None:
        path = self.root / "view" / name
        path.mkdir(mode=0o555)
        os.chown(path, self.uid, self.gid)

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
        output = run_dex(run, self.plugin / "bin/waydroid-verifier.dex", container_identity, guest,
                         "waydroid.manager.StorageIdentity", user)
        match = re.search(r"^STORAGE_UID:(\d+)\s*$", output, re.MULTILINE)
        group = run(["waydroid", "shell", "--", "id", "-g", "media_rw"], timeout=5).strip()
        if not group.isdecimal() or match is None:
            raise RuntimeError("Could not identify Android's shared storage permissions")
        helper = self._helper()
        self.namespace = Path(f"/proc/{guest[0]}/ns/mnt").stat().st_ino
        self.target = f"/data/media/{user}/Host"
        self.uid, self.gid = uid, owner.st_gid
        # MediaProvider opens the backing files on behalf of Android apps.
        self.android_uid, self.android_gid = match[1], group
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
            self._mount("", view, run)
            self._folder("Home")
            self._mount("Home", home, run)
            self.home = home
            self.ready = True
            self.refresh(run)
        except Exception:
            if self.guest is None:
                self.guard.recover()
            raise

    def refresh(self, run) -> None:
        if not self.ready or container_identity() != self.guest:
            return
        try:
            volumes = {volume.identity: volume for volume in mounted_volumes(run)}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            logging.getLogger(__name__).warning("External storage discovery unavailable: %s", error)
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

    def release(self, run) -> None:
        if self.guest is not None and container_identity() == self.guest:
            for name in reversed(tuple(self.mounts)):
                self._unmount(name, run)
        self.recover()

    def recover(self) -> None:
        self.guard.recover()
        self.guest = None
        self.ready = False
        self.mounts.clear()
        self.volumes.clear()
