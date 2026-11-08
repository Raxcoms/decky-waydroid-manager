import logging
from pathlib import Path
import subprocess
import uuid

from .container import LXC_PATH


def attach_command(*args: str) -> list[str]:
    return ["lxc-attach", "-P", str(LXC_PATH), "-n", "waydroid", "--clear-env", "--", *args]


class LaunchPolicy:
    def __init__(self, run, identify):
        self.run, self.identify = run, identify
        self.saved = None

    def android(self, *args: str) -> str:
        return self.run(["waydroid", "shell", "--", *args], timeout=5)

    def current(self) -> str | None:
        output = self.android("settings", "list", "global")
        return next((line.split("=", 1)[1] for line in output.splitlines()
                     if line.startswith("policy_control=")), None)

    def save(self, mode: str) -> None:
        identity = self.identify()
        if not identity:
            raise RuntimeError("WAYDROID_NOT_RUNNING")
        expected = "null*"
        if mode == "app":
            multiwindow = self.android("getprop", "persist.waydroid.multi_windows") or "false"
            expected = "immersive.status=*" if multiwindow == "false" else "immersive.full=*"
        self.saved = identity, self.current(), expected

    def restore(self) -> None:
        if self.saved is None:
            return
        identity, previous, expected = self.saved
        if self.identify() == identity and self.current() == expected and previous != expected:
            if previous is None:
                self.android("settings", "delete", "global", "policy_control")
            else:
                self.android("settings", "put", "global", "policy_control", previous)
        self.saved = None


def run_dex(run, helper: Path, identify, identity, main_class: str, *args: str, uid: str | None = None) -> str:
    if not identity or identify() != identity:
        raise RuntimeError("WAYDROID_NOT_RUNNING")
    # Stage trusted code in the guest's temporary /dev, outside the user-owned data mount.
    directory = f"/dev/.waydroid-manager-{uuid.uuid4().hex}"
    path = f"{directory}/helper.dex"
    try:
        with helper.open("rb") as source:
            run(attach_command("/system/bin/sh", "-c",
                               'set -e; /system/bin/mkdir -m 755 "$1"; /system/bin/cat > "$1/helper.dex"; /system/bin/chmod 444 "$1/helper.dex"',
                               "sh", directory), timeout=10, stdin=source)
        if identify() != identity:
            raise RuntimeError("WAYDROID_NOT_RUNNING")
        command = ["waydroid", "shell", *(["--uid", uid] if uid else []), "--", "env",
                   f"CLASSPATH={path}", "/system/bin/app_process", "/system/bin", main_class, *args]
        return run(command, timeout=15)
    finally:
        if identify() == identity:
            try:
                run(attach_command("/system/bin/rm", "-rf", directory), timeout=5)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                logging.getLogger(__name__).warning("Could not remove the temporary Android helper: %s", error)
