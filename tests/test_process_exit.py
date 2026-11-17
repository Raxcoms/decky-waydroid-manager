import os
import subprocess
import sys
import threading
import unittest

from waydroid_manager.proc import process_identity
from waydroid_manager.process_exit import wait_for_session_exit


@unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os, "pidfd_open"), "Requires Linux pidfds")
class ProcessExitTests(unittest.TestCase):
    def test_owner_exit_is_normal_and_guest_exit_is_an_error(self):
        for stopped in ("owner", "guest"):
            with self.subTest(stopped=stopped):
                children = {name: subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"],
                                                   stdin=subprocess.PIPE) for name in ("owner", "guest")}
                errors = []
                guest = process_identity(children["guest"].pid)
                owner = process_identity(children["owner"].pid)

                def wait():
                    try:
                        wait_for_session_exit(guest, owner)
                    except RuntimeError as error:
                        errors.append(str(error))

                thread = threading.Thread(target=wait)
                try:
                    thread.start()
                    children[stopped].stdin.close()
                    thread.join(timeout=3)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(errors, ["Waydroid session ended"] if stopped == "guest" else [])
                finally:
                    for child in children.values():
                        child.kill()
                        child.wait()
                        child.stdin.close()
                    thread.join(timeout=3)
