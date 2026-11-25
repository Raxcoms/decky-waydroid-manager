from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from waydroid_manager.elf_symbols import dynamic_symbols


class ElfSymbolTests(unittest.TestCase):
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
