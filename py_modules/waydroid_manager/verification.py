import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from .container import container_pid
from .proc import clean_env


class InstallCancelled(Exception):
    pass


def verification_dialog(activities: str, provider: str) -> bool:
    # GAPPS exposes this activity while Play Protect is waiting for a user decision.
    focused = re.search(r"(?:topResumedActivity|mResumedActivity)[^\n]*\bu0\s+([\w.]+)/([\w.$]+)", activities)
    return bool(focused and focused[1] == provider and focused[2].endswith(".PlayProtectDialogsActivity"))


def verification_id(dump: str, session: str, provider: str) -> int | None:
    requests, completed = set(), set()
    for record in dump.split("BroadcastRecord{")[1:]:
        if not re.search(r"caller=android [^\n]*\buid=1000\b", record):
            continue
        extras = re.search(r"extras: Bundle\[\{([^\n]+)\}\]", record)
        if not extras:
            continue
        values = dict(re.findall(r"android\.content\.pm\.extra\.(\w+)=([^,}]+)", extras[1]))
        value = values.get("VERIFICATION_ID", "")
        if not value.isdecimal() or int(value) > 2147483647:
            continue
        intent = re.search(r"^\s*Intent \{ act=android.intent.action.(PACKAGE_NEEDS_VERIFICATION|PACKAGE_VERIFIED) .*", record, re.MULTILINE)
        if not intent:
            continue
        if intent[1] == "PACKAGE_VERIFIED":
            completed.add(int(value))
            continue
        staged = re.search(r"/vmdl(\d+)\.tmp\b", intent[0])
        if staged and values.get("SESSION_ID") == staged[1] and re.search(rf"targetComp: \{{{re.escape(provider)}/", record):
            requests.add((staged[1], int(value), values.get("VERIFICATION_INSTALLER_UID")))
    pending = {item for item in requests if item[1] not in completed}
    owned = {item[1] for item in pending if item[0] == session and item[2] == "0"}
    if len(owned) > 1:
        raise RuntimeError("ANDROID_VERIFICATION_AMBIGUOUS")
    # A verifier can handle other installers too. Ask only when this is its sole pending request.
    return next(iter(owned)) if owned and len(pending) == 1 else None


def container_identity() -> tuple[int, str]:
    pid = container_pid()
    if not pid:
        raise RuntimeError("WAYDROID_NOT_RUNNING")
    return pid, (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]


class InstallVerification:
    def __init__(self, run, session: str, directory: Path, guest: str, helper: Path):
        self.run, self.session = run, session
        self.directory, self.guest, self.helper = directory, guest, helper
        self.identity = container_identity()
        self.request = None
        self.provider = None

    def android(self, *args: str) -> str:
        return self.run(["waydroid", "shell", "--", *args], timeout=10)

    def warning_pending(self) -> bool:
        configured = self.android("dumpsys", "package", "verifiers")
        provider = re.search(r"^\s*Required: ([\w.]+) \(uid=(\d+)\)", configured, re.MULTILINE)
        if not provider:
            return False
        if not verification_dialog(self.android("dumpsys", "activity", "activities"), provider[1]):
            return False
        request = verification_id(self.android("dumpsys", "activity", "broadcasts"), self.session, provider[1])
        if request is None:
            return False
        self.request, self.provider = request, provider
        return True

    def respond(self, approved: bool) -> None:
        if self.request is None or self.provider is None:
            raise RuntimeError("ANDROID_VERIFICATION_UNAVAILABLE")
        if container_identity() != self.identity:
            raise RuntimeError("WAYDROID_NOT_RUNNING")
        if not self.helper.is_file():
            raise RuntimeError("ANDROID_VERIFICATION_UNAVAILABLE")
        target = self.directory / "verifier.dex"
        shutil.copyfile(self.helper, target)
        self.directory.chmod(0o755)
        target.chmod(0o644)
        # Waydroid supplies Android's classpath and runs only this helper as the configured verifier.
        output = self.run([
            "waydroid", "shell", "--uid", self.provider[2], "--", "env",
            f"CLASSPATH={self.guest}/verifier.dex", "/system/bin/app_process", "/system/bin",
            "waydroid.manager.InstallVerifier", str(self.request), "2" if approved else "-1",
        ], timeout=15)
        if "VERIFICATION_SENT" not in output.splitlines():
            raise RuntimeError("ANDROID_VERIFICATION_UNAVAILABLE")


def commit_install(command: list[str], verifier, confirm, timeout: float = 300) -> str:
    process = subprocess.Popen(command, env=clean_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True)
    deadline = time.monotonic() + timeout
    asked = False
    try:
        while True:
            try:
                output, _ = process.communicate(timeout=1)
                if process.returncode:
                    raise RuntimeError(output.strip() or "PACKAGE_OPERATION_FAILED")
                return output.strip()
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise RuntimeError("PACKAGE_INSTALL_TIMEOUT")
                if process.poll() is None and not asked and verifier.warning_pending():
                    asked = True
                    approved = confirm(lambda: process.poll() is None)
                    if approved is not None and process.poll() is None:
                        verifier.respond(approved)
                        if not approved:
                            raise InstallCancelled()
                    deadline = max(deadline, time.monotonic() + 30)
    finally:
        if process.poll() is None:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate()
