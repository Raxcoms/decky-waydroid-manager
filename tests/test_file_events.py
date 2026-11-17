import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from waydroid_manager.file_events import FileEvents, process_handle
from waydroid_manager.proc import process_identity


@unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux event interfaces")
class FileEventTests(unittest.TestCase):
    def test_device_publication_and_explicit_shutdown_wake_the_waiter(self):
        with tempfile.TemporaryDirectory() as directory:
            changes = FileEvents([Path(directory)])
            try:
                self.assertEqual(changes.wait(timeout=0), [])
                (Path(directory) / "event0").touch()
                self.assertIn(changes.handle, changes.wait(timeout=1))
                changes.wake()
                self.assertIn(changes.read, changes.wait(timeout=1))
                self.assertEqual(changes.wait(timeout=0), [])
            finally:
                changes.close()

    @unittest.skipUnless(hasattr(os, "pidfd_open"), "Requires pidfd_open")
    def test_process_exit_wakes_without_a_polling_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            changes = FileEvents([Path(directory)])
            process = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
            handle = None
            try:
                handle = process_handle(process_identity(process.pid))
                if handle is None:
                    self.skipTest("The kernel has no process exit handles")
                process.stdin.close()
                self.assertIn(handle, changes.wait([handle], timeout=2))
                process.wait(timeout=2)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if handle is not None:
                    os.close(handle)
                changes.close()
