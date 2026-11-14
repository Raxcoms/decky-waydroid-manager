"""Temporary, explicitly invoked hardware smoke test for the display payload."""

import json
from pathlib import Path
import pwd
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.container import CONFIG_DIR, container_pid
from waydroid_manager.display_payload import inspect_vendor, select_payload
from waydroid_manager.guest import android_user_ready, keep_package_guest_running
from waydroid_manager.packages import install_apks
from waydroid_manager.verification import InstallVerification, commit_install
from waydroid_manager.proc import clean_env, steam_wayland_socket
from waydroid_manager.runtime_display import RuntimeDisplayLease
from waydroid_manager.second_screen import discover_external_display


def run(command, timeout=30, stdin=None):
    result = subprocess.run(command, env=clean_env(), stdin=stdin, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stdout.strip())
    return result.stdout.strip()


def smoke(root: Path, user: str, abandoned_sessions: list[str]):
    account = pwd.getpwnam(user)
    uid = account.pw_uid
    primary = steam_wayland_socket(uid)
    external = discover_external_display(uid, primary=primary)
    if not primary or not external:
        raise RuntimeError("Both host display sockets are required")
    if container_pid() is not None or "STOPPED" not in run(["waydroid", "status"]):
        raise RuntimeError("Close the Android session before running this test")
    identity = inspect_vendor(CONFIG_DIR, run)
    files = select_payload(root / "display-payloads", identity)
    user_command = ["runuser", "-u", user, "--", "env", f"HOME={account.pw_dir}",
                    f"XDG_RUNTIME_DIR=/run/user/{uid}",
                    f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                    f"WAYLAND_DISPLAY={primary}"]
    lease = RuntimeDisplayLease(CONFIG_DIR)
    package = "waydroid.manager.probe"
    installed = False
    failure = None

    def state(value, **details):
        (root / "smoke-state.json").write_text(json.dumps({"state": value, **details}))

    try:
        state("starting", primary=str(primary), external=str(external.socket))
        lease.acquire(files, external.socket, run, primary)
        run([*user_command, "systemd-run", "--user", "--collect", "--quiet",
             "--unit=waydroid-manager-display-smoke-session", "--property=KillMode=control-group",
             "env", f"WAYLAND_DISPLAY={primary}", "waydroid", "session", "start"])
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if android_user_ready(run):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Android did not boot with the external-display payload")
        run([*user_command, "waydroid", "show-full-ui"], timeout=15)
        baseline = run(["waydroid", "shell", "--", "cmd", "display", "get-displays"])
        state("booted", displays=baseline)
        for session in abandoned_sessions:
            if not session.isdecimal():
                raise RuntimeError("Invalid test install session")
            run(["waydroid", "shell", "--", "pm", "install-abandon", session])
        if f"package:{package}" in run(["waydroid", "shell", "--", "pm", "list", "packages", package]).splitlines():
            raise RuntimeError("The probe package already exists; preserve it before testing")
        with keep_package_guest_running(run):
            with (root / "display-probe.apk").open("rb") as source:
                def commit(session):
                    state("installing", session=session)
                    verifier = InstallVerification(run, session, root / "verifier.dex")
                    return commit_install(["waydroid", "shell", "--", "pm", "install-commit", session],
                                          verifier, lambda pending: True, timeout=120)
                install_apks(run, {"base.apk": source}, commit)
        installed = True
        run(["waydroid", "shell", "--", "setprop", "waydroid.external_display_active", "1"])
        deadline = time.monotonic() + 10
        displays = ""
        while time.monotonic() < deadline:
            displays = run(["waydroid", "shell", "--", "cmd", "display", "get-displays",
                            "android.hardware.display.category.PRESENTATION"])
            if re.search(r"Display id [1-9][0-9]*", displays):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Android did not announce its external display")
        run([*user_command, "waydroid", "show-full-ui"], timeout=15)
        run(["waydroid", "shell", "--", "am", "start", "-n", f"{package}/.ProbeActivity"])
        state("ready", baseline=baseline, external=displays)
        while not (root / "stop-smoke").exists():
            time.sleep(0.25)
    except Exception as error:
        failure = str(error)
        state("failed", error=str(error))
        raise
    finally:
        errors = []
        def cleanup(command, timeout=30):
            try:
                run(command, timeout=timeout)
            except Exception as error:
                errors.append(str(error))
        if container_pid() is not None:
            if installed:
                cleanup(["waydroid", "shell", "--", "am", "force-stop", package])
                cleanup(["waydroid", "shell", "--", "pm", "uninstall", package])
            cleanup(["busctl", "--system", "--timeout=20s", "call", "id.waydro.Container",
                 "/ContainerManager", "id.waydro.ContainerManager", "Stop", "b", "true"], timeout=25)
        subprocess.run([*user_command, "systemctl", "--user", "stop", "waydroid-manager-display-smoke-session"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        lease.recover()
        state("failed" if failure or errors else "cleaned", error=failure, cleanupErrors=errors)


if __name__ == "__main__":
    smoke(Path(sys.argv[1]), sys.argv[2], sys.argv[3:])
