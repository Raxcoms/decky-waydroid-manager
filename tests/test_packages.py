from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.packages import apk_members, stage_apks


class PackageArchiveTests(unittest.TestCase):
    def test_apk_staging_preserves_the_original_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.apk"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("AndroidManifest.xml", b"manifest")
            target = Path(directory) / "staged"
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(stage_apks(archive, apk_members(archive, ".apk"), target), ["base.apk"])
            self.assertEqual((target / "base.apk").read_bytes(), path.read_bytes())

    def test_split_names_cannot_collide_or_exhaust_the_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.xapk"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("one/base.apk", b"first")
                archive.writestr("two/base.apk", b"second")
            with zipfile.ZipFile(path) as archive:
                with self.assertRaisesRegex(RuntimeError, "XAPK_INVALID_NAMES"):
                    apk_members(archive, ".xapk")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("base.apk", b"first")
            target = Path(directory) / "staged"
            with zipfile.ZipFile(path) as archive, patch("waydroid_manager.packages.shutil.disk_usage", return_value=type("Usage", (), {"free": 1})()):
                with self.assertRaisesRegex(RuntimeError, "PACKAGE_NO_SPACE"):
                    stage_apks(archive, apk_members(archive, ".xapk"), target)
            self.assertFalse(target.exists())
