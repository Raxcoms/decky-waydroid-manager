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
# Android reserves display 0 for its default display on every device.
DEFAULT_DISPLAY = "0"


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

    def android(self, *args: str, timeout: int = 5) -> str:
        return self.run(["waydroid", "shell", "--", *args], timeout=timeout)

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
        previous = self.saved[1] if self.saved is not None and self.saved[0] == identity else self.current()
        self.saved = identity, previous, expected

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

    def present(self, package: str | None, whole_display: bool = False,
                companion: str | None = None, secondary_display: str | None = None) -> None:
        if self.saved is None or self.identify() != self.saved[0]:
            raise RuntimeError("WAYDROID_NOT_RUNNING")
        intent = ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME"]
        if package:
            intent = self._app_intent(package)
        companion_intent = None
        if companion:
            if not package or companion == package or not secondary_display or secondary_display == DEFAULT_DISPLAY:
                raise RuntimeError("The companion app requires a secondary display")
            companion_intent = self._app_intent(companion)
        # Dual-display sessions present Android outputs, without depending on task-layer metadata.
        active = "Waydroid" if whole_display else package or "Waydroid"
        self.android("setprop", "waydroid.active_apps", active)
        self.android("settings", "put", "global", "policy_control", self.saved[2])
        if companion_intent:
            self._start_activity(companion, secondary_display, companion_intent)
        # Present the primary app last so Android keeps it as the focused display.
        self._start_activity(package, DEFAULT_DISPLAY, intent)

    def _start_activity(self, package: str | None, display: str, intent: list[str]) -> None:
        command = ["am", "start", "-W", "--user", "current", "--display", display, *intent]
        output = self.android(*command, timeout=30)
        if re.search(r"^Error:", output, re.MULTILINE):
            raise RuntimeError(output.strip())
        activity = re.search(r"^Activity:\s+(\S+)", output, re.MULTILINE)
        if (not re.search(r"^Status:\s+ok\s*$", output, re.MULTILINE) or activity is None
                or (package and not activity[1].startswith(package + "/"))):
            raise RuntimeError("Android did not confirm the requested activity started")

    def _app_intent(self, package: str) -> list[str]:
        # Match Android's package launcher, including activities without CATEGORY_DEFAULT.
        component_pattern = re.compile(re.escape(package) + r"/[A-Za-z0-9_.$]+")
        for category in ("android.intent.category.INFO", "android.intent.category.LAUNCHER"):
            intent = ["-a", "android.intent.action.MAIN", "-c", category]
            output = self.android("cmd", "package", "query-activities", "--components", "--user", "current",
                                  *intent, "-p", package)
            component = next((line.strip() for line in output.splitlines()
                              if component_pattern.fullmatch(line.strip())), None)
            if component:
                return [*intent, "-n", component, "--activity-reset-task-if-needed"]
        raise RuntimeError(f"Android has no launch activity for {package}")

    def display_ready(self, display: str) -> bool:
        output = self.android("dumpsys", "activity", "activities")
        displays = re.split(r"^Display #(\d+).*?$", output, flags=re.MULTILINE)
        for index in range(1, len(displays), 2):
            if displays[index] != display:
                continue
            block = displays[index + 1]
            task = re.search(r"topResumedActivity=ActivityRecord\{(\S+)", block)
            if task is None:
                return False
            records = re.split(r"^\s*\* Hist\s+#\d+:\s*", block, flags=re.MULTILINE)
            record = next((record for record in records[1:]
                           if record.startswith(f"ActivityRecord{{{task[1]} ")), "")
            return "reportedDrawn=true" in record
        return False


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
