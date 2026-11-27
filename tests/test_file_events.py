import os
import runpy
import stat
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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

    def test_irrelevant_events_do_not_wake_the_waiter(self):
        with tempfile.TemporaryDirectory() as directory:
            changes = FileEvents([Path(directory)], lambda path, name: name.startswith("event"))
            try:
                (Path(directory) / "other").touch()
                self.assertEqual(changes.wait(timeout=0), [])
                (Path(directory) / "event0").touch()
                self.assertIn(changes.handle, changes.wait(timeout=1))
                changes.wake()
                self.assertIn(changes.read, changes.wait(timeout=1))
            finally:
                changes.close()

    def test_input_monitor_filters_unrelated_udev_entries(self):
        script = Path(__file__).resolve().parents[1] / "bin/waydroid-input-sync"
        matches = runpy.run_path(str(script))["input_event"]
        class Device:
            def stat(self):
                return SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_rdev=os.makedev(13, 64))
        with patch.object(Path, "glob", return_value=[Device()]):
            self.assertTrue(matches(Path("/run/udev/data"), "c13:64"))
            self.assertFalse(matches(Path("/run/udev/data"), "c13:65"))
            self.assertFalse(matches(Path("/run/udev/data"), "+unrelated:device"))
        self.assertTrue(matches(Path("/dev/input"), "event4"))
        self.assertTrue(matches(Path("/run/udev"), "data"))
        self.assertFalse(matches(Path("/run/udev"), "queue"))

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
