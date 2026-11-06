import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

loader = importlib.machinery.SourceFileLoader("input_sync", str(Path(__file__).resolve().parents[1] / "bin/waydroid-input-sync"))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = module
loader.exec_module(module)


class InputLayoutTests(unittest.TestCase):
    def test_virtual_controller_uses_its_xbox_layout_and_preserves_axis_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stock = root / "system/usr/keylayout/Vendor_045e_Product_028e.kl"
            stock.parent.mkdir(parents=True)
            data = b"key 307 BUTTON_X\nkey 308 BUTTON_Y\naxis 0x10 HAT_X\naxis 0x11 HAT_Y\naxis 0x03 Z flat 4096\n"
            stock.write_bytes(data)
            physical = root / "data/system/devices/keylayout/Vendor_2020_Product_3001.kl"
            physical.parent.mkdir(parents=True)
            physical.write_text("key 307 BUTTON_Y\nkey 544 DPAD_UP\n")
            self.assertEqual(module.steam_controller_layout(root), (stock.name, data))
            module.sync_keylayout(root, module.steam_controller_layout(root))
            self.assertEqual((physical.parent / "Vendor_28de_Product_11ff.kl").read_bytes(), data)
