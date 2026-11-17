import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from waydroid_manager.native_payload import NativePayload, select_native


class NativePayloadTests(unittest.TestCase):
    def test_selection_uses_android_abi_and_validates_built_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "android-33-arm64"
            payload.mkdir()
            header = bytearray(20)
            header[:6] = b"\x7fELF\x02\x01"
            struct.pack_into("<H", header, 18, 183)
            files = {}
            for name in ("hwcomposer.waydroid.so", "libhwc2on1adapter.so"):
                (payload / name).write_bytes(header)
                files[name] = hashlib.sha256(header).hexdigest()
            metadata = {"schemaVersion": 2, "sdk": 33, "elfMachine": 183,
                        "vndkVersion": "33", "recipeSha256": "a" * 64, "files": files,
                        "capabilities": ["external-presentation"]}
            (payload / "manifest.json").write_text(json.dumps(metadata))
            self.assertEqual(select_native(root, 33, "33", 183).root, payload)
            self.assertIn("external-presentation", select_native(root, 33, "33", 183).capabilities)
            metadata["densityReference"] = {"width": 1280, "height": 720, "dpi": 180}
            (payload / "manifest.json").write_text(json.dumps(metadata))
            self.assertEqual(NativePayload.load(payload).density_reference, (1280, 720, 180))
            metadata["densityReference"]["dpi"] = True
            (payload / "manifest.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(RuntimeError, "density reference"):
                NativePayload.load(payload)
            metadata["densityReference"]["dpi"] = 180
            (payload / "manifest.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(RuntimeError, "compatible"):
                select_native(root, 33, "32", 183)
            with self.assertRaisesRegex(RuntimeError, "compatible"):
                select_native(root, 33, "33", 62)
            (payload / "hwcomposer.waydroid.so").write_bytes(header + b"changed")
            with self.assertRaisesRegex(RuntimeError, "failed validation"):
                NativePayload.load(payload)
