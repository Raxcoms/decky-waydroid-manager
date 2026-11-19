import base64
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from waydroid_manager.icon_cache import IconCache, source_digest


def icon_png():
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 512, 512, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + b"\0" * 2048) * 512)) + chunk(b"IEND", b""))


class IconCacheTests(unittest.TestCase):
    def test_cache_tracks_the_exact_exported_icon_and_package(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = IconCache(Path(directory))
            source = source_digest("original Android export")
            content = icon_png()
            cache.put("example.app", source, content)
            self.assertEqual(cache.get("example.app", source), "data:image/png;base64," + base64.b64encode(content).decode())
            self.assertIsNone(cache.get("example.other", source))
            self.assertIsNone(cache.get("example.app", source_digest("new Android export")))

    def test_invalid_icon_or_cache_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = IconCache(Path(directory))
            with self.assertRaises(ValueError):
                cache.put("example.app", source_digest("icon"), b"not an icon")
            with self.assertRaises(ValueError):
                cache.put("../../private", source_digest("icon"), icon_png())

    def test_symlink_is_never_returned_as_a_cached_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            cache = IconCache(home)
            cache.directory.mkdir(parents=True)
            source = source_digest("icon")
            target = home / "original.png"
            target.write_bytes(icon_png())
            cache.path("example.app", source).symlink_to(target)
            self.assertIsNone(cache.get("example.app", source))
