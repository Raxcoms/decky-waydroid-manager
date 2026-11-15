from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from native_symbols import validate


class NativeSymbolTests(unittest.TestCase):
    def test_only_sdk_exports_and_declared_waydroid_extensions_are_allowed(self):
        with patch("native_symbols.symbols", side_effect=[{"standard"}, {"standard", "waydroid"}]):
            validate(Path("nm"), Path("composer.so"), Path("sdk"), ["waydroid"])
        with patch("native_symbols.symbols", side_effect=[{"standard"}, {"standard", "undeclared"}]):
            with self.assertRaisesRegex(RuntimeError, "undeclared"):
                validate(Path("nm"), Path("composer.so"), Path("sdk"), ["waydroid"])
