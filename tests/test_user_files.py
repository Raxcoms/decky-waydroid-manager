from pathlib import Path
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py_modules"))
from waydroid_manager.user_files import open_as_user


@unittest.skipUnless(hasattr(socket, "SCM_RIGHTS"), "Requires Unix file descriptor passing")
class UserFileTests(unittest.TestCase):
    def test_selected_file_is_opened_by_the_user_and_survives_path_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / "example.apk"
            path.write_bytes(b"first package")
            with open_as_user(ROOT / "bin/waydroid-user-files", home, path) as source:
                path.unlink()
                path.write_bytes(b"replacement")
                self.assertEqual(source.read(), b"first package")

    def test_worker_rejects_a_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            real = home / "real.apk"
            real.touch()
            path = home / "alias.apk"
            path.symlink_to(real)
            with self.assertRaises(RuntimeError):
                with open_as_user(ROOT / "bin/waydroid-user-files", home, path):
                    self.fail("Opened a symlink as an install file")
