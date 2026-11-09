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
  systemd-run:*) touch running ;;
  systemctl:*is-active*) [ -f running ] && [ ! -f owner_lost ] ;;
  systemctl:*stop*) echo stop >> calls ;;
  waydroid:status)
    if [ -f running ]; then
      state=RUNNING
      if [ -f freezing ]; then state=FREEZING; fi
      printf 'Session: RUNNING\nContainer: %s\nWayland display: %s\n' "$state" "$WAYLAND_DISPLAY"
    else
      echo 'Session: STOPPED'
    fi
    ;;
  'waydroid:app list')
    echo list >> calls
    case "$SCENARIO" in
      stopped) rm -f running ;;
      owner_lost) touch owner_lost ;;
      ready|ends|freezing) if [ "$(grep -c '^list$' calls)" -ge 3 ]; then echo 'Name: Test app'; fi ;;
      locked) echo 'Name: Test app' ;;
    esac
    exit 0
    ;;
  waydroid:show-full-ui|waydroid:app\\ launch\\ *)
    echo "$*" >> calls
    if [ "$SCENARIO" = ends ]; then rm -f running; fi
    if [ "$SCENARIO" = freezing ]; then touch freezing; fi
    ;;
  sleep:*) : ;;
  *) exit 2 ;;
esac
"""


@unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux shell tools")
class GameSessionTests(unittest.TestCase):
    def run_session(self, scenario, mode="full"):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "calls").touch()
            if scenario == "foreign":
                (directory / "running").touch()
            command = directory / "mock-command"
            command.write_text(MOCK_COMMAND)
            command.chmod(0o755)
            for name in ("waydroid", "systemctl", "systemd-run", "sleep"):
                (directory / name).symlink_to(command)
            runner = directory / RUNNER.name
            runner.write_text(RUNNER.read_text())
            service = directory / "waydroid-service"
            service.write_text(
                '#!/bin/sh\n'
                'if [ "$1" = --release ]; then echo stop >> "$WAYDROID_MANAGER_LOG_DIR/calls"; exit 0; fi\n'
                'if [ "$SCENARIO" = locked ] && [ "$1" = --policy ] && [ "$2" != restore ]; then\n'
                '  calls="$WAYDROID_MANAGER_LOG_DIR/calls"\n'
                '  echo unlock-check >> "$calls"\n'
                '  if [ "$(grep -c unlock-check "$calls")" -lt 3 ]; then exit 3; fi\n'
                'fi\n'
            )
            service.chmod(0o755)
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
            result = subprocess.run(["bash", str(runner)], env=env, capture_output=True, text=True, timeout=20)
            return result, (directory / "calls").read_text().splitlines()

    def test_presentation_waits_for_android_apps(self):
        for mode, command in (("full", "show-full-ui"), ("app", "app launch test.package")):
            with self.subTest(mode=mode):
                result, calls = self.run_session("ready", mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, ["list", "list", "list", command, "stop"])

    def test_never_launches_if_the_owned_session_disappears(self):
        for scenario in ("stopped", "owner_lost"):
            with self.subTest(scenario=scenario):
                result, calls = self.run_session(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Android did not become ready", result.stderr)
                self.assertEqual(calls, ["list", "stop"])

    def test_foreign_session_is_left_alone(self):
        result, calls = self.run_session("foreign")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Close the running Waydroid session", result.stderr)
        self.assertEqual(calls, [])

    def test_app_list_does_not_allow_launch_before_unlock(self):
        result, calls = self.run_session("locked", "app")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["list", "unlock-check"] * 3 + ["app launch test.package", "stop"])

    def test_freezing_is_not_a_stopped_container(self):
        result, calls = self.run_session("freezing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["list", "list", "list", "show-full-ui", "stop"])

    def test_shortcut_exits_if_android_dies_after_presentation(self):
        result, calls = self.run_session("ends")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Waydroid session ended", result.stderr)
        self.assertEqual(calls, ["list", "list", "list", "show-full-ui", "stop"])
