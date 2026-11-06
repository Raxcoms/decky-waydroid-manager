import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from .container import container_pid
from .proc import clean_env


def verification_id(dump: str, session: str, provider: str) -> int | None:
    requests = set()
    for record in dump.split("BroadcastRecord{")[1:]:
        intent = re.search(r"^\s*Intent \{ act=android.intent.action.PACKAGE_NEEDS_VERIFICATION .*", record, re.MULTILINE)
        if not intent or not re.search(rf"/vmdl{re.escape(session)}\.tmp\b", intent[0]):
            continue
        if not re.search(rf"targetComp: \{{{re.escape(provider)}/", record):
            continue
        if not re.search(r"caller=android [^\n]*\buid=1000\b", record):
            continue
        extras = re.search(r"extras: Bundle\[\{([^\n]+)\}\]", record)
        if not extras:
            continue
        values = dict(re.findall(r"android\.content\.pm\.extra\.(\w+)=([^,}]+)", extras[1]))
        if values.get("SESSION_ID") != session or values.get("VERIFICATION_INSTALLER_UID") != "0":
            continue
        value = values.get("VERIFICATION_ID", "")
        if value.isdecimal() and int(value) <= 2147483647:
            requests.add(int(value))
    if len(requests) > 1:
        raise RuntimeError("ANDROID_VERIFICATION_AMBIGUOUS")
    return next(iter(requests), None)


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
        self.approved = False

    def android(self, *args: str) -> str:
        return self.run(["waydroid", "shell", "--", *args], timeout=10)

    def approve_pending(self) -> None:
        if self.approved:
            return
        configured = self.android("dumpsys", "package", "verifiers")
        provider = re.search(r"^\s*Required: ([\w.]+) \(uid=(\d+)\)", configured, re.MULTILINE)
        if not provider:
            return
        request = verification_id(self.android("dumpsys", "activity", "broadcasts"), self.session, provider[1])
        if request is None:
            return
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
            "waydroid", "shell", "--uid", provider[2], "--", "env",
            f"CLASSPATH={self.guest}/verifier.dex", "/system/bin/app_process", "/system/bin",
            "waydroid.manager.InstallVerifier", str(request), "2",
        ], timeout=15)
        if "VERIFICATION_SENT" not in output.splitlines():
            raise RuntimeError("ANDROID_VERIFICATION_UNAVAILABLE")
        self.approved = True


def commit_install(command: list[str], verifier, timeout: float = 300) -> str:
    process = subprocess.Popen(command, env=clean_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True)
    deadline = time.monotonic() + timeout
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
                if process.poll() is None:
                    verifier.approve_pending()
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
