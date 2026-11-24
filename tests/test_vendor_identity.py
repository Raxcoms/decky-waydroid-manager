import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from waydroid_manager.display_payload import inspect_vendor
from waydroid_manager.native_payload import NativePayload


@unittest.skipUnless(shutil.which("cc"), "Requires a C compiler for ELF fixtures")
class VendorIdentityTests(unittest.TestCase):
    def test_effective_binder_override_rejects_an_incompatible_native_build(self):
        self.inspect_overrides(False)

    def test_vendor_overrides_supply_properties_and_component_identities(self):
        self.inspect_overrides(True)

    def inspect_overrides(self, vendor_overrides):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            libraries = {}
            symbol = "_ZTVN7android8hardware7IBinderE"
            for name, size in (("base", 224), ("override", 232)):
                source = root / (name + ".c")
                source.write_text(f"char {symbol}[{size}];\n")
                library = root / (name + ".so")
                subprocess.run(["cc", "-shared", "-fPIC", str(source), "-o", str(library)], check=True)
                libraries[name] = library.read_bytes()
            images = root / "images"
            images.mkdir()
            (images / "vendor.img").touch()
            (root / "waydroid.cfg").write_text(f"[waydroid]\nimages_path={images}\n")
            properties = ("ro.vendor.build.fingerprint=fixture\nro.vendor.build.version.sdk=33\n"
                          "ro.vndk.version=33\n")
            override = root / "overlay/system/apex/com.android.vndk.current/lib64/libhidlbase.so"
            override.parent.mkdir(parents=True)
            override.write_bytes(libraries["override"])
            if vendor_overrides:
                vendor = root / "overlay/vendor"
                (vendor / "lib64/hw").mkdir(parents=True)
                (vendor / "build.prop").write_text(properties.replace("fixture", "override").replace("33", "34"))
                for path in ("lib64/hw/hwcomposer.waydroid.so", "lib64/libhwc2on1adapter.so"):
                    (vendor / path).write_bytes(libraries["override"])

            def run(command, **kwargs):
                _, source, target = command[2].split(" ", 2)
                data = (properties.encode() if source == "/build.prop" else
                        libraries["base"] if source.endswith(".so") else b"resource")
                Path(target).write_bytes(data)
                return ""

            def native_only(command, **kwargs):
                self.assertNotIn(".apk", command[2])
                return run(command, **kwargs)
            native = inspect_vendor(root, native_only, display_resources=False)
            self.assertEqual((native.system_ui_digest, native.framework_digest), ("", ""))
            identity = inspect_vendor(root, run)
            self.assertEqual(native.binder_vtable_size, identity.binder_vtable_size)
            self.assertEqual(identity.binder_vtable_size, 232)
            payload = NativePayload(root, identity.sdk, identity.vndk, identity.machine, "fixture",
                                    binder_vtable_size=224)
            with self.assertRaisesRegex(RuntimeError, "Binder interface"):
                payload.validate_runtime(identity)
            if vendor_overrides:
                expected = hashlib.sha256(libraries["override"]).hexdigest()
                self.assertEqual((identity.fingerprint, identity.sdk, identity.vndk), ("override", 34, "34"))
                self.assertEqual(identity.composer_digest, expected)
                self.assertEqual(identity.adapter_digest, expected)
