import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "bin/waydroid-game-session"
MOCK_COMMAND = """#!/bin/bash
cd "$WAYDROID_MANAGER_LOG_DIR" || exit 1
case "${0##*/}:$*" in
  systemd-run:*) touch running android-ready ;;
  systemctl:*is-active*) [ -f running ] && [ ! -f owner_lost ] ;;
  systemctl:*stop*) echo stop >> calls ;;
  waydroid:status)
    if [ -f running ]; then echo 'Session: RUNNING'; else echo 'Session: STOPPED'; fi
    ;;
  'waydroid:app list')
    echo list >> calls
    case "$SCENARIO" in
      stopped) rm -f running ;;
      owner_lost) touch owner_lost ;;
      ready) if [ "$(grep -c '^list$' calls)" -ge 3 ]; then echo 'Name: Test app'; fi ;;
    esac
    exit 0
    ;;
  waydroid:show-full-ui|waydroid:app\\ launch\\ *) echo "$*" >> calls ;;
  sleep:*) : ;;
  *) exit 2 ;;
esac
"""


@unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux shell tools")
class GameSessionTests(unittest.TestCase):
    def run_session(self, scenario, mode="full"):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            command = directory / "mock-command"
            command.write_text(MOCK_COMMAND)
            command.chmod(0o755)
            for name in ("waydroid", "systemctl", "systemd-run", "sleep"):
                (directory / name).symlink_to(command)
            env = {
                **os.environ,
                "PATH": f"{tmp}:{os.environ['PATH']}",
                "USER": "test",
                "LOGNAME": "test",
                "DISPLAY": ":99",
                "XDG_RUNTIME_DIR": tmp,
                "DBUS_SESSION_BUS_ADDRESS": "unused",
                "GAMESCOPE_WAYLAND_DISPLAY": "test-socket",
                "WAYDROID_MANAGER_STEAM_OWNER_PID": "0",
                "WAYDROID_MANAGER_SESSION_UNIT": "test-unit",
                "WAYDROID_MANAGER_SESSION_RUNNER": "unused",
                "WAYDROID_MANAGER_LOG_DIR": tmp,
                "WAYDROID_MANAGER_MODE": mode,
                "WAYDROID_MANAGER_PACKAGE": "test.package",
                "SCENARIO": scenario,
            }
            result = subprocess.run(["bash", str(RUNNER)], env=env, capture_output=True, text=True, timeout=20)
            return result, (directory / "calls").read_text().splitlines()

    def test_presentation_waits_for_android_apps(self):
        for mode, command in (("full", "show-full-ui"), ("app", "app launch test.package")):
            with self.subTest(mode=mode):
                result, calls = self.run_session("ready", mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, ["stop", "list", "list", "list", command, "stop"])

    def test_never_launches_if_the_owned_session_disappears(self):
        for scenario in ("stopped", "owner_lost"):
            with self.subTest(scenario=scenario):
                result, calls = self.run_session(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Waydroid session stopped before launch", result.stderr)
                self.assertEqual(calls, ["stop", "list", "stop"])

    def test_never_launches_if_android_apps_stay_unavailable(self):
        result, calls = self.run_session("not_ready")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Android app list did not become ready", result.stderr)
        self.assertEqual(calls, ["stop", *(["list"] * 20), "stop"])
