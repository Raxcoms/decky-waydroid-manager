import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.display_payload import VendorIdentity, digest, select_payload


class DisplayPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payload = self.root / "android-33"
        self.payload.mkdir()
        self.library = self.payload / "hwcomposer.waydroid.so"
        header = bytearray(20)
        header[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", header, 18, 183)
        self.library.write_bytes(header)
        (self.payload / "libhwc2on1adapter.so").write_bytes(header)
        (self.payload / "WaydroidManagerExternalDisplay.apk").write_bytes(b"test overlay")
        (self.payload / "WaydroidManagerNavigationBar.apk").write_bytes(b"test navigation overlay")
        (self.payload / "wayland_tablet.idc").write_text("touch.displayId = local:1\n")
        (self.payload / "display_settings.xml").write_text('<displays><display name="local:1" shouldShowSystemDecors="true" /></displays>')
        self.identity = VendorIdentity("test/vendor/fingerprint", 33, "a" * 64, 183)
        self.metadata = {
            "vendorFingerprint": self.identity.fingerprint,
            "sdk": 33,
            "stockComposerSha256": self.identity.composer_digest,
            "elfMachine": 183,
            "composerSha256": digest(self.library),
            "stockAdapterSha256": "",
            "stockSystemUiSha256": "",
            "adapterSha256": digest(self.payload / "libhwc2on1adapter.so"),
            "overlaySha256": digest(self.payload / "WaydroidManagerExternalDisplay.apk"),
            "inputConfigSha256": digest(self.payload / "wayland_tablet.idc"),
            "displaySettingsSha256": digest(self.payload / "display_settings.xml"),
            "navigationOverlaySha256": digest(self.payload / "WaydroidManagerNavigationBar.apk"),
        }
        self.write_manifest()

    def write_manifest(self):
        (self.payload / "manifest.json").write_text(json.dumps(self.metadata))

    def test_requires_all_installed_vendor_identifiers(self):
        for field, value in [("vendorFingerprint", "other"), ("sdk", 30),
                             ("stockComposerSha256", "b" * 64), ("elfMachine", 62),
                             ("stockSystemUiSha256", "different System UI")]:
            with self.subTest(field=field):
                saved = self.metadata[field]
                self.metadata[field] = value
                self.write_manifest()
                with self.assertRaisesRegex(RuntimeError, "No compatible"):
                    select_payload(self.root, self.identity)
                self.metadata[field] = saved

    def test_selects_validated_library_for_vendor_overlay(self):
        self.assertEqual(select_payload(self.root, self.identity), {
            "vendor/lib64/hw/hwcomposer.waydroid.so": self.library,
            "vendor/lib64/libhwc2on1adapter.so": self.payload / "libhwc2on1adapter.so",
            "system/product/overlay/WaydroidManagerExternalDisplay.apk": self.payload / "WaydroidManagerExternalDisplay.apk",
            "system/usr/idc/wayland_tablet.idc": self.payload / "wayland_tablet.idc",
            "vendor/etc/display_settings.xml": self.payload / "display_settings.xml",
            "system/product/overlay/WaydroidManagerNavigationBar.apk": self.payload / "WaydroidManagerNavigationBar.apk",
        })

    def test_rejects_modified_library(self):
        with self.library.open("ab") as file:
            file.write(b"modified")
        with self.assertRaisesRegex(RuntimeError, "failed validation"):
            select_payload(self.root, self.identity)
