from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from waydroid_manager.density import CONFIG, prepare_density
from waydroid_manager.density_settings import density_settings


class DensityTests(unittest.TestCase):
    def test_density_curve_preserves_other_display_settings(self):
        source = b'<displayConfiguration><screenBrightnessDefault>0.5</screenBrightnessDefault></displayConfiguration>'
        root = ET.fromstring(density_settings(source, 1280, 720, 240))
        self.assertEqual(root.findtext("screenBrightnessDefault"), "0.5")
        self.assertEqual([root.findtext("densityMapping/density/" + key) for key in ("width", "height", "density")],
                         ["1280", "720", "240"])

    def test_existing_image_density_curve_is_preserved(self):
        source = b'<displayConfiguration><densityMapping><density><width>1</width></density></densityMapping></displayConfiguration>'
        self.assertEqual(density_settings(source, 1280, 720, 180), source)

    def test_namespaced_configuration_is_merged(self):
        source = b'<displayConfiguration xmlns="urn:display"><screenBrightnessDefault>0.5</screenBrightnessDefault></displayConfiguration>'
        root = ET.fromstring(density_settings(source, 1280, 720, 180))
        self.assertEqual(root.findtext("{urn:display}densityMapping/{urn:display}density/{urn:display}density"), "180")

    def test_runtime_uses_image_density_and_leaves_existing_overlay_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "waydroid"
            config.mkdir()
            (config / "waydroid.cfg").write_text("[waydroid]\nimages_path=/images\n[properties]\n")
            existing = config / "overlay" / CONFIG
            existing.parent.mkdir(parents=True)
            source = b"<displayConfiguration><screenBrightnessDefault>0.5</screenBrightnessDefault></displayConfiguration>"
            existing.write_bytes(source)
            def run(args, **kwargs):
                return "ro.sf.lcd_density=240" if args[2] == "cat /build.prop" else ""
            staging = Path(directory) / "staging"
            prepare_density(config, staging, (1280, 720, 180), run)
            self.assertEqual(existing.read_bytes(), source)
            root = ET.parse(staging / CONFIG).getroot()
            self.assertEqual(root.findtext("densityMapping/density/density"), "240")

    def test_explicit_user_density_prevents_automatic_scaling(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            (config / "waydroid.cfg").write_text("[waydroid]\nimages_path=/images\n[properties]\nro.sf.lcd_density=320\n")
            prepare_density(config, config / "staging", (1280, 720, 180), lambda *args: self.fail("Image inspection was not needed"))
            self.assertFalse((config / "staging" / CONFIG).exists())

    def test_product_image_configuration_takes_priority_over_vendor_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            (config / "waydroid.cfg").write_text("[waydroid]\nimages_path=/images\n")
            vendor = config / "overlay/vendor/etc/displayconfig/default.xml"
            vendor.parent.mkdir(parents=True)
            vendor.write_text("<displayConfiguration />")
            original = "<displayConfiguration><densityMapping><density><width>1280</width><height>720</height><density>240</density></density></densityMapping></displayConfiguration>"
            def run(args, **kwargs):
                if args[2].startswith("dump /product/etc/displayconfig/default.xml "):
                    Path(args[2].split(" ", 2)[2]).write_text(original)
                return "debugfs 1.47.0"
            prepare_density(config, config / "staging", (1280, 720, 180), run)
            self.assertEqual((config / "staging" / CONFIG).read_text(), original)

    def test_missing_image_configuration_ignores_debugfs_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            (config / "waydroid.cfg").write_text("[waydroid]\nimages_path=/images\n")
            prepare_density(config, config / "staging", (1280, 720, 180),
                            lambda *args, **kwargs: "debugfs 1.47.0\nFile not found by ext2_lookup")
            root = ET.parse(config / "staging" / CONFIG).getroot()
            self.assertEqual(root.findtext("densityMapping/density/density"), "180")
