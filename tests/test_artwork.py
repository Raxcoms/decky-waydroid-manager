from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.artwork import apk_images, missing_artwork


class ArtworkTests(unittest.TestCase):
    def test_user_artwork_is_preserved_and_logo_position_is_not_an_image(self):
        with tempfile.TemporaryDirectory() as directory:
            grid = Path(directory)
            (grid / "123p.jpg").write_bytes(b"cover")
            (grid / "123_logo.json").write_text("{}")
            self.assertEqual(missing_artwork(grid, 123), ["hero", "logo", "landscape"])

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
