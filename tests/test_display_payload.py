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
        self.identity = VendorIdentity("test/vendor/fingerprint", 33, "a" * 64, 183)
        self.metadata = {
            "vendorFingerprint": self.identity.fingerprint,
            "sdk": 33,
            "stockComposerSha256": self.identity.composer_digest,
            "elfMachine": 183,
            "composerSha256": digest(self.library),
        }
        self.write_manifest()

    def write_manifest(self):
        (self.payload / "manifest.json").write_text(json.dumps(self.metadata))

    def test_requires_all_installed_vendor_identifiers(self):
        for field, value in [("vendorFingerprint", "other"), ("sdk", 30),
                             ("stockComposerSha256", "b" * 64), ("elfMachine", 62)]:
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
        })

    def test_rejects_modified_library(self):
        with self.library.open("ab") as file:
            file.write(b"modified")
        with self.assertRaisesRegex(RuntimeError, "failed validation"):
            select_payload(self.root, self.identity)
