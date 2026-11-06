from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.input import InputNodes, RuntimeKeylayout, STEAM_LAYOUT


class InputLayoutTests(unittest.TestCase):
    def test_layout_uses_a_runtime_view_and_removes_only_matching_legacy_data(self):
        with tempfile.TemporaryDirectory() as directory:
            process = Path(directory)
            root = process / "root"
            stock = root / "system/usr/keylayout/Vendor_045e_Product_028e.kl"
            stock.parent.mkdir(parents=True)
            content = b"key 307 BUTTON_X\nkey 308 BUTTON_Y\naxis 0x10 HAT_X\naxis 0x03 Z flat 4096\n"
            stock.write_bytes(content)
            (root / "dev").mkdir()
            legacy = root / "data/system/devices/keylayout"
            legacy.mkdir(parents=True)
            (legacy / STEAM_LAYOUT).write_bytes(content)
            (legacy / ".waydroid-manager-steam-layout").write_text(stock.name)
            calls = []
            def run(pid, *args):
                calls.append(args)
                if args[0].endswith("/mount"):
                    mount_root = args[-2].removeprefix("/dev")
                    (process / "mountinfo").write_text(f"1 0 0:1 {mount_root} /system/usr/keylayout rw - tmpfs tmpfs rw")
            view = RuntimeKeylayout(123, root, run)
            view.open()
            runtime = view.directory
            self.assertEqual((runtime / "keylayout" / STEAM_LAYOUT).read_bytes(), content)
            self.assertFalse((legacy / STEAM_LAYOUT).exists())
            self.assertFalse((stock.parent / STEAM_LAYOUT).exists())
            self.assertEqual(stock.read_bytes(), content)
            view.close()
            self.assertFalse(runtime.exists())
            self.assertEqual(calls[-1], ("/system/bin/umount", "-l", "/system/usr/keylayout"))

    def test_user_layout_is_preserved_without_mounting_or_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stock = root / "system/usr/keylayout/Vendor_045e_Product_028e.kl"
            stock.parent.mkdir(parents=True)
            stock.write_bytes(b"stock")
            legacy = root / "data/system/devices/keylayout" / STEAM_LAYOUT
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"user custom layout")
            view = RuntimeKeylayout(123, root, lambda *args: self.fail("Custom layout was overridden"))
            view.open()
            self.assertEqual(legacy.read_bytes(), b"user custom layout")
            self.assertIsNone(view.directory)

    @unittest.skipIf(os.name == "nt", "Requires Unix device metadata")
    def test_private_input_nodes_are_restored_and_external_replacements_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "dev/input"
            inputs.mkdir(parents=True)
            original = inputs / "event1"
            original.write_bytes(b"existing Android node")
            with patch("waydroid_manager.input.os.mknod", side_effect=lambda path, *_: path.write_bytes(b"runtime node"), create=True), patch("waydroid_manager.input.os.chown", create=True), patch("waydroid_manager.input.stat.S_ISCHR", return_value=True):
                nodes = InputNodes(root)
                nodes.sync({"event1": 0})
                self.assertEqual(original.read_bytes(), b"runtime node")
                nodes.close()
                self.assertEqual(original.read_bytes(), b"existing Android node")
                nodes = InputNodes(root)
                nodes.sync({"event1": 0})
                replacement = inputs / "replacement"
                replacement.write_bytes(b"external replacement")
                replacement.replace(original)
                nodes.close()
                self.assertEqual(original.read_bytes(), b"external replacement")
