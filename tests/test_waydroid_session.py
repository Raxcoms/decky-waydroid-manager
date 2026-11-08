import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "bin/waydroid-session"
MOCK_COMMAND = """#!/bin/bash
cd "$WAYDROID_MANAGER_LOG_DIR" || exit 1
case "${0##*/}:$*" in
  'waydroid:prop get persist.waydroid.multi_windows') [ -f configured ] && echo true || echo false ;;
  'waydroid:prop set persist.waydroid.multi_windows true') touch configured; echo prop >> calls ;;
  'waydroid:session start')
    echo start >> calls
    starts=$(cat starts 2>/dev/null || echo 0)
    starts=$((starts + 1))
    echo "$starts" > starts
    echo 'Android with user 0 is ready'
    while [ ! -f "stop-$starts" ]; do /bin/sleep 0.01; done
    ;;
  'waydroid:session stop') starts=$(cat starts); touch "stop-$starts"; echo stop >> calls ;;
  waydroid:status) echo 'Session: RUNNING' ;;
  sleep:*) : ;;
  *) exit 2 ;;
esac
"""


@unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux shell tools")
class WaydroidSessionTests(unittest.TestCase):
    def test_enables_multi_window_before_starting_the_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "calls").touch()
            command = directory / "mock-command"
            command.write_text(MOCK_COMMAND)
            command.chmod(0o755)
            for name in ("waydroid", "sleep"):
                (directory / name).symlink_to(command)
            env = {
                **os.environ,
                "PATH": f"{tmp}:{os.environ['PATH']}",
                "WAYDROID_MANAGER_LOG_DIR": tmp,
            }
            process = subprocess.Popen(["bash", str(RUNNER)], env=env)
            ready = directory / "android-ready"
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            process.terminate()
            process.wait(timeout=5)
            self.assertEqual((directory / "calls").read_text().splitlines(), ["start", "prop", "stop", "start", "stop"])


if __name__ == "__main__":
    unittest.main()
