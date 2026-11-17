from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from waydroid_manager.shared_home import SharedHome


class SharedHomeTests(unittest.TestCase):
    def test_unfinished_mount_cannot_be_reused_as_a_ready_share(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = SharedHome(Path("config"), Path("tools"), Path(directory) / "lease")
            lease.guest = (123, "start")
            with patch("waydroid_manager.shared_home.container_identity", return_value=lease.guest):
                with self.assertRaisesRegex(RuntimeError, "did not finish"):
                    lease.ensure(Path(directory), 1000, Path("display"), Mock())

    def test_release_unmounts_only_the_same_guest_and_cleans_guard(self):
        for current in ((123, "start"), (123, "replaced"), None):
            with self.subTest(current=current):
                lease = SharedHome(Path("config"), Path("tools"), Path("lease"))
                lease.guard = Mock()
                lease.guest = (123, "start")
                lease.mount = (456, "/data/media/7/HostHome", "99", "100")
                run = Mock()
                with patch("waydroid_manager.shared_home.container_identity", return_value=current):
                    lease.release(run)
                if current == (123, "start"):
                    run.assert_called_once_with(["lease/home-mount", "unmount", "123", "456",
                                                 "/data/media/7/HostHome", "99", "100"], timeout=10)
                else:
                    run.assert_not_called()
                lease.guard.recover.assert_called_once()
                self.assertIsNone(lease.guest)
                self.assertIsNone(lease.mount)
