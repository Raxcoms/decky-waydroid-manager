import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from native_dependencies import extract, fetch


class NativeDependencyTests(unittest.TestCase):
    def test_download_is_verified_and_cached_by_content(self):
        content = b"pinned upstream input"
        entry = {"name": "source", "url": "https://upstream.example/source.tar.gz",
                 "sha256": hashlib.sha256(content).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            with patch("native_dependencies.urllib.request.urlopen", return_value=io.BytesIO(content)) as download:
                cached = fetch(entry, Path(directory))
                self.assertEqual(cached.read_bytes(), content)
                self.assertEqual(fetch(entry, Path(directory)), cached)
                download.assert_called_once()
            cached.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                fetch(entry, Path(directory))

    def test_failed_download_never_becomes_a_cache_entry(self):
        entry = {"name": "source", "url": "https://upstream.example/source.tar.gz", "sha256": "0" * 64}
        with tempfile.TemporaryDirectory() as directory:
            with patch("native_dependencies.urllib.request.urlopen", return_value=io.BytesIO(b"incorrect")):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    fetch(entry, Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_unsafe_archive_cannot_write_outside_its_staging_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                entry = tarfile.TarInfo("../outside")
                entry.size = 3
                output.addfile(entry, io.BytesIO(b"bad"))
            with self.assertRaisesRegex(RuntimeError, "Unsafe"):
                extract(archive, root / "source")
            self.assertFalse((root / "outside").exists())
            self.assertFalse((root / "source").exists())

    def test_explicit_source_exclusions_do_not_extract_external_formatter_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                link = tarfile.TarInfo("project/.clang-format")
                link.type, link.linkname = tarfile.SYMTYPE, "../../external"
                output.addfile(link)
                entry = tarfile.TarInfo("project/source.cpp")
                entry.size = 4
                output.addfile(entry, io.BytesIO(b"code"))
            extract(archive, root / "source", strip_root=True, exclude=(".clang-format",))
            self.assertEqual((root / "source/source.cpp").read_bytes(), b"code")
            self.assertFalse((root / "source/.clang-format").exists())
