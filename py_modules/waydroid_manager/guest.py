from contextlib import contextmanager
import logging
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

from .container import LXC_PATH, container_identity
from .proc import clean_env, process_identity


GUEST_STARTING = "WAYDROID_GUEST_STARTING"


def attach_command(*args: str) -> list[str]:
    return ["lxc-attach", "-P", str(LXC_PATH), "-n", "waydroid", "--clear-env", "--", *args]


def stream_to_guest(run, source, *args: str, timeout: int) -> str:
    # LXC changes stdin ownership and permissions, so pass a pipe instead of the file.
    with subprocess.Popen(["cat"], stdin=source, stdout=subprocess.PIPE, env=clean_env()) as reader:
        try:
            output = run(attach_command(*args), timeout=timeout, stdin=reader.stdout)
            reader.stdout.close()
            if reader.wait(timeout=5):
                raise RuntimeError("Could not read the file sent to Android")
            return output
        finally:
            if reader.poll() is None:
                reader.kill()


@contextmanager
def keep_package_guest_running(run):
    identity = container_identity()
    if not identity:
        raise RuntimeError("WAYDROID_NOT_RUNNING")
    stop = threading.Event()

    def watch() -> None:
        # Android can suspend the hidden session while Package Manager is still working.
        status = ["lxc-info", "-P", str(LXC_PATH), "-n", "waydroid", "-sH"]
        while not stop.is_set() and process_identity(identity[0]) == identity:
            try:
                if run(status, timeout=3) == "FROZEN" and container_identity() == identity and not stop.is_set():
                    run(["waydroid", "container", "unfreeze"], timeout=5)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                logging.getLogger(__name__).warning("Could not resume the Android package session: %s", error)
                return
            stop.wait(2)

    thread = threading.Thread(target=watch, name="waydroid-package-wake")
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def android_user_ready(run) -> bool:
    check = """
        [ "$(getprop sys.boot_completed)" = 1 ] || exit 1
        user=$(cmd activity get-current-user) || exit 1
        case "$user" in ""|*[!0-9]*) exit 1 ;; esac
        [ "$(cmd activity get-started-user-state "$user")" = RUNNING_UNLOCKED ] && echo ANDROID_READY
    """
    try:
        output = run(["waydroid", "shell", "--", "/system/bin/sh", "-c", check], timeout=5)
    except (RuntimeError, subprocess.TimeoutExpired):
        return False
    return "ANDROID_READY" in output.splitlines()


def set_media_volume_max(run) -> None:
    command = ["waydroid", "shell", "--", "cmd", "media_session", "volume"]
    volume = re.compile(r"\bvolume is (\d+) in range \[\d+\.\.(\d+)\]")
    current = volume.search(run([*command, "--get"], timeout=5))
    if not current:
        raise RuntimeError("Android did not report its media volume range")
    if current[1] == current[2]:
        return
    run([*command, "--set", current[2]], timeout=5)
    # Android saves volume asynchronously. Keep the setup session open for the write.
    time.sleep(1)
    verified = volume.search(run([*command, "--get"], timeout=5))
    if not verified or verified[1] != verified[2]:
        raise RuntimeError("Android media volume did not reach its maximum")


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
            stream_to_guest(
                run, source, "/system/bin/sh", "-c",
                'set -e; /system/bin/mkdir -m 755 "$1"; /system/bin/cat > "$1/helper.dex"; /system/bin/chmod 444 "$1/helper.dex"',
                "sh", directory, timeout=10,
            )
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
