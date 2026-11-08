from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.image import owned_directory, require_unmounted, require_unredirected, run_init


class ImageRemovalSafetyTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux directory descriptors")
    def test_data_directory_remains_pinned_when_renamed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "share"
            data.mkdir()
            (data / "marker").write_text("original")
            with owned_directory(data, os.getuid()) as pinned:
                data.rename(root / "old")
                data.mkdir()
                (data / "marker").write_text("replacement")
                self.assertEqual((pinned / "marker").read_text(), "original")

    @unittest.skipIf(os.name == "nt", "Requires a Linux-style symlink")
    def test_rejects_a_redirected_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "actual").mkdir()
            (root / "redirected").symlink_to(root / "actual", target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "redirected"):
                require_unredirected(root / "redirected" / "waydroid")

    def test_rejects_a_mount_inside_waydroid_data(self):
        with tempfile.TemporaryDirectory() as directory:
            mountinfo = Path(directory) / "mountinfo"
            mountinfo.write_text(r"1 0 0:1 / /var/lib/waydroid/rootfs/shared\040data rw - tmpfs tmpfs rw" + "\n")
            with self.assertRaisesRegex(RuntimeError, "shared data"):
                require_unmounted((Path("/var/lib/waydroid"),), mountinfo)
            require_unmounted((Path("/var/lib/waydroid-other"),), mountinfo)


class ImageProgressTests(unittest.TestCase):
    def test_progress_uses_waydroid_download_measurements_and_verification_stage(self):
        progress = []
        script = (
            "print('[12:00:00] Downloading system');"
            "print('\\r[Downloading] 22.5 MB/ 90 MB', end='');"
            "print('\\r[Downloading] 90 MB/90 MB');"
            "print('[12:00:05] Validating system image');"
            "print('[12:00:06] Downloading vendor');"
            "print('\\r[Downloading] 5 MB/10 MB');"
        )
        run_init([sys.executable, "-c", script], lambda *state: progress.append(state), timeout=10)
        self.assertEqual(progress, [
            ("downloading", None), ("downloading", 25), ("downloading", 100),
            ("finalizing", None), ("downloading", None), ("downloading", 50),
        ])

    def test_failed_initialization_keeps_cli_error(self):
        with self.assertRaisesRegex(RuntimeError, "No images found on system channel"):
            run_init([
                sys.executable, "-c", "print('No images found on system channel'); raise SystemExit(1)",
            ], lambda *_: None, timeout=10)
