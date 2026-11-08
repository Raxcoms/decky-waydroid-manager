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
  systemd-run:*) touch active; echo start >> calls ;;
  systemctl:*show*) [ -f active ] && echo active ;;
  systemctl:*stop*) rm -f active; echo stop >> calls ;;
  'waydroid:app list') echo list >> calls; echo 'Name: Test app' ;;
  'waydroid:app launch test.package') echo launch >> calls ;;
  'waydroid:shell -- am force-stop test.package') echo force-stop >> calls ;;
  sleep:*) : ;;
  *) exit 2 ;;
esac
"""


@unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux shell tools")
class GameSessionTests(unittest.TestCase):
    def run_session(self, *, existing_launch=False):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            leases = directory / "launches"
            leases.mkdir()
            if existing_launch:
                (leases / "other").write_text(f"{os.getpid()}\n")
            (directory / "calls").touch()
            (directory / "active").touch() if existing_launch else None
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
                "XDG_RUNTIME_DIR": tmp,
                "DBUS_SESSION_BUS_ADDRESS": "unused",
                "WAYDROID_MANAGER_STEAM_OWNER_PID": "0",
                "WAYDROID_MANAGER_SESSION_UNIT": "test-unit",
                "WAYDROID_MANAGER_SESSION_RUNNER": "unused",
                "WAYDROID_MANAGER_LOG_DIR": tmp,
                "WAYDROID_MANAGER_LAUNCH_DIR": str(leases),
                "WAYDROID_MANAGER_MODE": "app",
                "WAYDROID_MANAGER_PACKAGE": "test.package",
            }
            result = subprocess.run(["bash", str(RUNNER), "gamescope"], env=env, capture_output=True, text=True, timeout=20)
            return result, (directory / "calls").read_text().splitlines()

    def test_last_shortcut_stops_the_shared_session(self):
        result, calls = self.run_session()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["start", "list", "launch", "force-stop", "stop"])

    def test_shortcut_exit_keeps_another_app_session_running(self):
        result, calls = self.run_session(existing_launch=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["list", "launch", "force-stop"])


if __name__ == "__main__":
    unittest.main()
