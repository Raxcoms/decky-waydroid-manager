"""Expose home through Android storage for the owned container's lifetime."""

import json
from pathlib import Path
import re
import shutil

from .container import container_identity
from .display_payload import digest, elf_machine
from .runtime_display import RuntimeDisplayLease


class SharedHome:
    def __init__(self, config: Path, tools: Path, root: Path = Path("/run/waydroid-manager-home")):
        self.tools, self.root = tools, root
        self.guard = RuntimeDisplayLease(config, root)
        self.guest: tuple[int, str] | None = None
        self.mount: tuple[int, str, str, str] | None = None

    def _helper(self) -> Path:
        machine = elf_machine(Path("/usr/bin/python3").resolve())
        bundle = self.tools / str(machine)
        helper = bundle / "home-mount"
        metadata = json.loads((bundle / "manifest.json").read_text())
        if (helper.is_symlink() or metadata.get("elfMachine") != machine
                or digest(helper) != metadata.get("files", {}).get("home-mount") or elf_machine(helper) != machine):
            raise RuntimeError("The host folder mount helper failed validation")
        return helper

    def ensure(self, home: Path, uid: int, display: Path, run) -> None:
        guest = container_identity()
        if not guest:
            raise RuntimeError("WAYDROID_NOT_RUNNING")
        if self.guest == guest:
            if self.mount is None:
                raise RuntimeError("Home sharing did not finish. Close the running Waydroid shortcuts before retrying")
            return
        if self.root.exists():
            raise RuntimeError("The previous shared home session is still closing")
        home = home.resolve(strict=True)
        owner = home.stat()
        if owner.st_uid != uid:
            raise RuntimeError("The home folder is not owned by the Steam login user")
        user = run(["waydroid", "shell", "--", "cmd", "activity", "get-current-user"], timeout=5).strip()
        provider = run(["waydroid", "shell", "--", "cmd", "package", "list", "packages", "--user", user,
                        "-U", "com.android.externalstorage"], timeout=5)
        match = re.search(r"^package:com\.android\.externalstorage uid:(\d+)\s*$", provider, re.MULTILINE)
        group = run(["waydroid", "shell", "--", "id", "-g", "media_rw"], timeout=5).strip()
        if not user.isascii() or not user.isdecimal() or not group.isdecimal() or match is None:
            raise RuntimeError("Could not identify Android's shared storage permissions")
        namespace = Path(f"/proc/{guest[0]}/ns/mnt").stat().st_ino
        target = f"/data/media/{user}/HostHome"
        helper = self._helper()
        self.root.mkdir(mode=0o700)
        invoked = False
        try:
            staged = self.root / "home-mount"
            shutil.copyfile(helper, staged)
            staged.chmod(0o700)
            self.guard.start_guard(run, display)
            if container_identity() != guest:
                raise RuntimeError("Android restarted while preparing home sharing")
            self.guest = guest
            invoked = True
            output = run([str(staged), "mount", str(guest[0]), str(namespace), str(home), target,
                          str(owner.st_uid), match[1], str(owner.st_gid), group], timeout=10).split()
            if len(output) != 2 or not all(value.isdecimal() for value in output):
                raise RuntimeError("The home mount helper returned an invalid mount identity")
            self.mount = namespace, target, *output
        except Exception:
            if not invoked:
                self.guard.recover()
            raise

    def release(self, run) -> None:
        if self.guest is not None and container_identity() == self.guest:
            if self.mount is None:
                return
            namespace, target, mount_id, created = self.mount
            run([str(self.root / "home-mount"), "unmount", str(self.guest[0]), str(namespace),
                 target, mount_id, created], timeout=10)
        self.guard.recover()
        self.guest = self.mount = None

    def recover(self) -> None:
        self.guard.recover()
        self.guest = self.mount = None
