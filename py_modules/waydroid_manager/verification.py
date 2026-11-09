import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from .container import container_identity
from .guest import run_dex
from .packages import check_result
from .proc import clean_env


class InstallCancelled(Exception):
    pass


def verification_dialog(activities: str, provider: str) -> bool:
    # GAPPS exposes this activity while Play Protect is waiting for a user decision.
    focused = re.search(r"(?:topResumedActivity|mResumedActivity)[^\n]*\bu0\s+([\w.]+)/([\w.$]+)", activities)
    return bool(focused and focused[1] == provider and focused[2].endswith(".PlayProtectDialogsActivity"))


def active_install_sessions(dump: str) -> set[str]:
    active = re.split(r"(?m)^(?:Finalized|Historical) install sessions:", dump, maxsplit=1)[0]
    sessions = re.split(r"(?m)^\s*Active Session (\d+):\s*$", active)
    # Android can keep verification alive after an abandoned session is marked destroyed.
    return {session for session, details in zip(sessions[1::2], sessions[2::2])
            if re.search(r"\bmCommitted=true\b", details)
            and re.search(r"\b(?:mDestroyed=false|mStageDirInUse=true)\b", details)}


def verification_id(dump: str, session: str, provider: str, active_sessions: set[str]) -> int | None:
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
    pending = {item for item in requests if item[0] in active_sessions and item[1] not in completed}
    owned = {item[1] for item in pending if item[0] == session and item[2] == "0"}
    if len(owned) > 1:
        raise RuntimeError("ANDROID_VERIFICATION_AMBIGUOUS")
    # A verifier can handle other installers too. Ask only when this is its sole pending request.
    return next(iter(owned)) if owned and len(pending) == 1 else None


class InstallVerification:
    def __init__(self, run, session: str, helper: Path):
        self.run, self.session = run, session
        self.helper = helper
        self.identity = container_identity()
        self.request = None
        self.provider = None

    def android(self, *args: str) -> str:
        return self.run(["waydroid", "shell", "--", *args], timeout=10)

    def configured_provider(self) -> tuple[str, str] | None:
        configured = self.android("dumpsys", "package", "verifiers")
        provider = re.search(r"^\s*Required: ([\w.]+) \(uid=(\d+)\)", configured, re.MULTILINE)
        return (provider[1], provider[2]) if provider else None

    def pending_request(self, provider: str, *, allow_other_sessions: bool = False) -> int | None:
        active = active_install_sessions(self.android("dumpsys", "package", "installs"))
        if self.session not in active:
            return None
        sessions = {self.session} if allow_other_sessions else active
        return verification_id(self.android("dumpsys", "activity", "broadcasts"), self.session, provider, sessions)

    def warning_pending(self) -> bool:
        provider = self.configured_provider()
        if not provider or not verification_dialog(self.android("dumpsys", "activity", "activities"), provider[0]):
            return False
        request = self.pending_request(provider[0])
        if request is None:
            return False
        self.request, self.provider = request, provider
        return True

    def respond(self, approved: bool) -> None:
        if self.request is None or self.provider is None:
            raise RuntimeError("ANDROID_VERIFICATION_UNAVAILABLE")
        request, provider = self.request, self.provider
        if not self.warning_pending() or (self.request, self.provider) != (request, provider):
            raise RuntimeError("ANDROID_VERIFICATION_UNAVAILABLE")
        self.send_response(request, provider[1], approved)

    def reject_pending(self) -> None:
        provider = self.configured_provider()
        if provider:
            # A timeout can reject its own request even when another install is waiting.
            request = self.pending_request(provider[0], allow_other_sessions=True)
            if request is not None:
                self.send_response(request, provider[1], False)

    def send_response(self, request: int, uid: str, approved: bool) -> None:
        if not self.identity or container_identity() != self.identity:
            raise RuntimeError("WAYDROID_NOT_RUNNING")
        if not self.helper.is_file():
            raise RuntimeError("ANDROID_VERIFICATION_UNAVAILABLE")
        output = run_dex(self.run, self.helper, container_identity, self.identity,
                         "waydroid.manager.InstallVerifier", str(request), "2" if approved else "-1", uid=uid)
        if "VERIFICATION_SENT" not in output.splitlines():
            raise RuntimeError("ANDROID_VERIFICATION_UNAVAILABLE")


def commit_install(command: list[str], verifier, confirm, timeout: float = 300) -> str:
    process = subprocess.Popen(command, env=clean_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True)
    deadline = time.monotonic() + timeout
    asked = False
    responded = False
    succeeded = False
    try:
        while True:
            try:
                output, _ = process.communicate(timeout=1)
                output = output.strip()
                if process.returncode:
                    raise RuntimeError(output or "PACKAGE_OPERATION_FAILED")
                check_result(output)
                succeeded = True
                return output
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise RuntimeError("PACKAGE_INSTALL_TIMEOUT")
                if process.poll() is None and not asked and verifier.warning_pending():
                    asked = True
                    approved = confirm(lambda: process.poll() is None)
                    if approved is not None and process.poll() is None:
                        verifier.respond(approved)
                        responded = True
                        if not approved:
                            raise InstallCancelled()
                    deadline = max(deadline, time.monotonic() + 30)
    finally:
        if not succeeded and not responded:
            try:
                verifier.reject_pending()
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                logging.getLogger(__name__).warning("Could not reject pending Android verification: %s", error)
        if process.poll() is None:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate()
