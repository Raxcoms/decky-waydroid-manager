from contextlib import contextmanager
import os
import re
import select
import subprocess
import time

from .guest import attach_command, staged_dex
from .proc import clean_env


def wait_for_guard(process, timeout=10):
    deadline = time.monotonic() + timeout
    output = b""
    while b"INPUT_GUARDED\n" not in output.splitlines(keepends=True):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
            raise RuntimeError("Android input guard did not become ready")
        chunk = os.read(process.stdout.fileno(), 4096)
        if not chunk:
            raise RuntimeError("Android input guard failed: " + output.decode(errors="replace")[-1000:])
        output = (output + chunk)[-4096:]


@contextmanager
def guard_guest_input(run, helper, identify, identity):
    if not identity or identify() != identity:
        raise RuntimeError("WAYDROID_NOT_RUNNING")
    dump = run(attach_command("/system/bin/dumpsys", "input"), timeout=5)
    state = re.search(r"^\s*DispatchEnabled:\s*(true|false)\s*$", dump, re.MULTILINE)
    if not state:
        raise RuntimeError("Android did not report its input dispatch state")
    if state[1] == "false":
        yield
        return
    with staged_dex(run, helper, identify, identity) as path:
        command = attach_command("/system/bin/env", f"CLASSPATH={path}", "/system/bin/app_process",
                                 "/system/bin", "waydroid.manager.InputGuard")
        with subprocess.Popen(command, env=clean_env(), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              start_new_session=True) as process:
            try:
                wait_for_guard(process)
                yield
            finally:
                # Closing stdin releases the guest guard before removing its staged code.
                try:
                    output, _ = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        output, _ = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                        raise RuntimeError("Android input guard did not exit")
                if identify() == identity and (process.returncode or b"INPUT_RESTORED" not in output.splitlines()):
                    raise RuntimeError("Android input guard did not confirm input restoration")
