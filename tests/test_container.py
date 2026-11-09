from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.container import vendor_overlay_warning


class VendorOverlayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.staged = self.root / "overlay/vendor"
        self.target = self.root / "rootfs/vendor"
        self.mountinfo = self.root / "mountinfo"
        self.vendor_mount = f"41 38 7:0 / {self.target} ro - ext4 /dev/loop0 ro\n"

    def stage_library(self):
        library = self.staged / "lib64/egl/libEGL_mesa.so"
        library.parent.mkdir(parents=True)
        library.touch()

    def test_ordinary_vendor_image_does_not_need_an_overlay(self):
        self.mountinfo.write_text(self.vendor_mount)
        self.assertIsNone(vendor_overlay_warning(self.root, self.mountinfo))

    def test_reports_staged_libraries_missing_from_the_vendor_mount(self):
        self.stage_library()
        self.mountinfo.write_text(self.vendor_mount)
        self.assertIn("vendor overlay is not mounted", vendor_overlay_warning(self.root, self.mountinfo))

    def test_accepts_overlay_with_the_staged_vendor_as_a_lower_layer(self):
        self.stage_library()
        self.mountinfo.write_text(
            self.vendor_mount + f"42 41 0:42 / {self.target} rw - overlay overlay rw,lowerdir={self.staged}:{self.target}\n"
        )
        self.assertIsNone(vendor_overlay_warning(self.root, self.mountinfo))

    def test_no_warning_when_the_mount_is_not_visible(self):
        self.stage_library()
        self.mountinfo.write_text("")
        self.assertIsNone(vendor_overlay_warning(self.root, self.mountinfo))
