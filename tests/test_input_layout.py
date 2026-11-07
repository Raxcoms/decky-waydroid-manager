from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.input import ControllerDevice, InputNodes, RuntimeKeylayout, STEAM_LAYOUT, attach


class InputLayoutTests(unittest.TestCase):
    def test_existing_steam_layout_does_not_require_the_xbox_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = root / "system/usr/keylayout" / STEAM_LAYOUT
            layout.parent.mkdir(parents=True)
            layout.write_bytes(b"native Steam layout")
            view = RuntimeKeylayout(123, root, lambda *args: self.fail("Existing layout was replaced"))
            view.open()
            self.assertIsNone(view.directory)

    def test_slow_container_attach_is_reported_as_a_recoverable_input_error(self):
        with patch("waydroid_manager.input.container_pid", return_value=123), patch(
            "waydroid_manager.input.subprocess.run", side_effect=subprocess.TimeoutExpired("lxc-attach", 5)
        ):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                attach(123, "/system/bin/mount")

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
    def test_delegated_controller_is_restored_and_platform_nodes_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "dev/input"
            inputs.mkdir(parents=True)
            original = inputs / "event4"
            alias = inputs / "waydroid-manager-event1"
            original.write_bytes(b"existing Android node")
            steam = {"event1": ControllerDevice(0, "input1")}
            shared = {"event4": ControllerDevice(0, "input4")}
            with patch("waydroid_manager.input.os.mknod", side_effect=lambda path, *_: path.write_bytes(b"runtime node"), create=True), patch("waydroid_manager.input.os.chown", create=True), patch("waydroid_manager.input.stat.S_ISCHR", return_value=True):
                nodes = InputNodes(root)
                nodes.sync(steam, shared)
                self.assertFalse(original.exists())
                self.assertEqual(alias.read_bytes(), b"runtime node")
                nodes.close(shared)
                self.assertFalse(alias.exists())
                self.assertEqual(original.read_bytes(), b"existing Android node")
                nodes = InputNodes(root)
                nodes.sync(steam, shared)
                original.write_bytes(b"external replacement")
                nodes.close(shared)
                self.assertEqual(original.read_bytes(), b"external replacement")

    @unittest.skipIf(os.name == "nt", "Requires Unix device metadata")
    def test_ambiguous_controller_mapping_preserves_platform_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "dev/input"
            inputs.mkdir(parents=True)
            (inputs / "event4").write_bytes(b"platform node")
            with patch("waydroid_manager.input.stat.S_ISCHR", return_value=True):
                nodes = InputNodes(root)
                nodes.sync(
                    {"event1": ControllerDevice(0, "input1"), "event2": ControllerDevice(0, "input2")},
                    {"event4": ControllerDevice(0, "input4")},
                )
                self.assertEqual(sorted(node.name for node in inputs.iterdir() if node.is_file()), ["event4"])
                nodes.close()

    @unittest.skipIf(os.name == "nt", "Requires Unix device metadata")
    def test_recreated_controller_with_the_same_evdev_number_is_republished(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dev/input").mkdir(parents=True)
            creates, permissions, publications = [], set(), []
            def create(path, *_):
                creates.append(path)
                path.write_bytes(str(len(creates)).encode())
            def chown(path, *_):
                permissions.add(path)
            link = os.link
            def publish(source, target):
                self.assertIn(source, permissions)
                self.assertEqual(source.stat().st_mode & 0o777, 0o660)
                self.assertFalse(target.exists())
                publications.append(target)
                link(source, target)
            with patch("waydroid_manager.input.os.mknod", side_effect=create), patch("waydroid_manager.input.os.chown", side_effect=chown), patch("waydroid_manager.input.os.link", side_effect=publish), patch("waydroid_manager.input.stat.S_ISCHR", return_value=True):
                nodes = InputNodes(root)
                nodes.sync({"event1": ControllerDevice(0, "input20/event1")})
                nodes.sync({"event1": ControllerDevice(0, "input20/event1")})
                self.assertEqual(len(publications), 1)
                nodes.sync({"event1": ControllerDevice(0, "input21/event1")})
                self.assertEqual(len(publications), 2)
                alias = root / "dev/input/waydroid-manager-event1"
                self.assertEqual(alias.read_bytes(), b"2")
                alias.unlink()
                nodes.sync({"event1": ControllerDevice(0, "input21/event1")})
                self.assertEqual(alias.read_bytes(), b"3")
                nodes.close()
                self.assertFalse(alias.exists())
