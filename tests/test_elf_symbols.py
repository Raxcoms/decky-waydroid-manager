from pathlib import Path
import shutil
import subprocess
import struct
import tempfile
import unittest

from waydroid_manager.elf_symbols import dynamic_symbols, undefined_symbols


class ElfSymbolTests(unittest.TestCase):
    def test_reads_32_bit_defined_and_undefined_symbols(self):
        names = b"\0exported\0imported\0weak_import\0"
        symbols = b"".join((
            struct.pack("<IIIBBH", 1, 0, 4, 0x12, 0, 1),
            struct.pack("<IIIBBH", 10, 0, 0, 0x12, 0, 0),
            struct.pack("<IIIBBH", 19, 0, 0, 0x22, 0, 0),
        ))
        data = bytearray(52 + 3 * 40 + len(symbols) + len(names))
        data[:6] = b"\x7fELF\x01\x01"
        struct.pack_into("<I", data, 32, 52)
        struct.pack_into("<HH", data, 46, 40, 3)
        symbol_offset = 52 + 3 * 40
        name_offset = symbol_offset + len(symbols)
        struct.pack_into("<IIIIIIIIII", data, 52 + 40, 0, 11, 0, 0, symbol_offset,
                         len(symbols), 2, 0, 4, 16)
        struct.pack_into("<IIIIIIIIII", data, 52 + 80, 0, 3, 0, 0, name_offset,
                         len(names), 0, 0, 1, 0)
        data[symbol_offset:name_offset] = symbols
        data[name_offset:] = names
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "audio.so"
            library.write_bytes(data)
            self.assertEqual(dynamic_symbols(library), {"exported": 4})
            self.assertEqual(undefined_symbols(library), {"imported"})
    @unittest.skipUnless(shutil.which("cc"), "A host C compiler is needed")
    def test_reads_defined_symbols_and_excludes_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "library.c"
            source.write_text('extern int imported(void); int exported(void) { return imported(); }')
            library = source.with_suffix(".so")
            subprocess.run(["cc", "-shared", "-fPIC", str(source), "-o", str(library)], check=True)
            symbols = dynamic_symbols(library)
            self.assertGreater(symbols["exported"], 0)
            self.assertNotIn("imported", symbols)
            library.write_bytes(library.read_bytes()[:64])
            with self.assertRaisesRegex(RuntimeError, "ELF"):
                dynamic_symbols(library)
