from pathlib import Path
import hashlib
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.artwork import apk_images, missing_artwork, package_apks, persistent_apks, prune_artwork


class ArtworkTests(unittest.TestCase):
    def test_offline_apks_include_base_and_splits_from_the_latest_package_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            old = data / "app/example.app-old"
            new = data / "app/~~token/example.app-new"
            sibling = data / "app/~~token/example.application-other"
            for path in (old, new, sibling):
                path.mkdir(parents=True)
                (path / "base.apk").write_bytes(b"apk")
            (new / "split_assets.apk").write_bytes(b"split")
            (new / "base.dm").write_bytes(b"metadata")
            os.utime(old, (10, 10))
            os.utime(new, (20, 20))
            self.assertEqual(persistent_apks(data, "example.app"), [new / "base.apk", new / "split_assets.apk"])
            self.assertEqual(persistent_apks(data, "../example.app"), [])

    @unittest.skipIf(os.name == "nt", "Requires Unix symlinks")
    def test_offline_apks_do_not_follow_package_or_split_links_outside_android_data(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            outside = Path(directory) / "outside"
            outside.mkdir()
            (outside / "base.apk").write_bytes(b"apk")
            app = data / "app"
            app.mkdir(parents=True)
            (app / "example.app-link").symlink_to(outside, target_is_directory=True)
            self.assertEqual(persistent_apks(data, "example.app"), [])
            valid = app / "example.app-valid"
            valid.mkdir()
            (valid / "base.apk").write_bytes(b"apk")
            (valid / "split.apk").symlink_to(outside / "base.apk")
            self.assertEqual(persistent_apks(data, "example.app"), [valid / "base.apk"])

    def test_package_paths_keep_the_container_root_link_and_reject_traversal(self):
        root = Path("/proc/123/root")
        paths = "package:/data/app/base.apk\npackage:/data/app/split.apk\npackage:/../../outside.apk\npackage://outside.apk\nlog text"
        self.assertEqual(package_apks(root, paths), [root / "data/app/base.apk", root / "data/app/split.apk"])

    def test_user_artwork_is_preserved_and_logo_position_is_not_an_image(self):
        with tempfile.TemporaryDirectory() as directory:
            grid = Path(directory)
            (grid / "123p.jpg").write_bytes(b"cover")
            (grid / "123_logo.json").write_text("{}")
            self.assertEqual(missing_artwork(grid, 123), ["hero", "logo", "landscape"])

    def test_removed_shortcuts_delete_only_unchanged_generated_artwork_in_the_active_library(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            grid = home / "library/grid"
            other_grid = home / "other-library/grid"
            for parent in (grid, other_grid):
                parent.mkdir(parents=True)
            removed = grid / "123p.png"
            custom = grid / "123_hero.png"
            active = grid / "456.png"
            other = other_grid / "123p.png"
            for path in (removed, custom, active, other):
                path.write_bytes(b"generated")
            records = {str(path.relative_to(home)): hashlib.sha256(b"generated").hexdigest()
                       for path in (removed, custom, active, other)}
            custom.write_bytes(b"custom")
            prune_artwork(home, grid, records, {456})
            self.assertFalse(removed.exists())
            self.assertEqual(custom.read_bytes(), b"custom")
            self.assertEqual(set(records), {str(path.relative_to(home)) for path in (active, other)})
            self.assertTrue(active.exists() and other.exists())

    def test_apk_filter_ignores_ad_sdk_artwork_and_tiny_placeholders(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "base.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("assets/Launcher/EndLogo.png", b"x" * 2048)
                archive.writestr("res/drawable/app_banner.png", b"x" * 2048)
                archive.writestr("res/drawable/google_logo.png", b"x" * 2048)
                archive.writestr("assets/splash.png", b"x" * 95)
                archive.writestr("assets/not_artwork.bin", b"x" * 2048)
            images = apk_images([apk])
            self.assertEqual([image["name"] for image in images], ["assets/Launcher/EndLogo.png", "res/drawable/app_banner.png"])

    def test_apk_image_size_is_bounded_before_decompression(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "base.apk"
            with zipfile.ZipFile(apk, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("assets/huge_banner.png", b"x" * (5 * 1024 * 1024))
            self.assertEqual(apk_images([apk]), [])
