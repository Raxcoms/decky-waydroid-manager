from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from waydroid_manager.shared_storage import SharedStorage


class SharedStorageTests(unittest.TestCase):
    def test_unfinished_mount_cannot_be_reused_as_a_ready_share(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = SharedStorage(Path("config"), Path("tools"), Path(directory) / "lease")
            lease.guest = (123, "start")
            with patch("waydroid_manager.shared_storage.container_identity", return_value=lease.guest):
                with self.assertRaisesRegex(RuntimeError, "did not finish"):
                    lease.ensure(Path(directory), 1000, Path("display"), Mock())

    def test_release_unmounts_only_the_same_guest_and_cleans_guard(self):
        for current in ((123, "start"), (123, "replaced"), None):
            with self.subTest(current=current):
                lease = SharedStorage(Path("config"), Path("tools"), Path("lease"))
                lease.guard = Mock()
                lease.guest = (123, "start")
                lease.process = (456, "provider")
                lease.mounts = {"Home": (456, "/data/user/7/waydroid.manager.storage/files/Host/Home", "99", "100")}
                run = Mock()
                with patch("waydroid_manager.shared_storage.container_identity", return_value=current), patch("waydroid_manager.shared_storage.process_identity", return_value=lease.process):
                    lease.release(run)
                if current == (123, "start"):
                    run.assert_called_once_with(["lease/home-mount", "unmount", "456", "456",
                                                 "/data/user/7/waydroid.manager.storage/files/Host/Home", "99", "100"], timeout=10)
                else:
                    run.assert_not_called()
                lease.guard.recover.assert_called_once()
                self.assertIsNone(lease.guest)
                self.assertEqual(lease.mounts, {})
