import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.artwork import ARTWORK_VERSION, artwork_updates, prune_artwork
from waydroid_manager.state import StateStore


class ArtworkTests(unittest.TestCase):
    def test_missing_and_untouched_legacy_slots_are_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            grid = home / "grid"
            grid.mkdir()
            (grid / "123p.png").write_bytes(b"generated")
            (grid / "123_hero.png").write_bytes(b"custom")
            (grid / "123.png").write_bytes(b"generated")
            (grid / "123.webp").write_bytes(b"custom")
            (grid / "123.json").write_text("{}")
            digest = hashlib.sha256(b"generated").hexdigest()
            records = {str(Path("grid") / name): digest for name in ("123p.png", "123_hero.png", "123.png")}
            self.assertEqual(artwork_updates(home, grid, 123, records), (["portrait"], False))
            for version in range(1, ARTWORK_VERSION):
                records[str(Path("grid") / "123p.png")] = f"{version}:{digest}"
                self.assertEqual(artwork_updates(home, grid, 123, records), (["portrait"], False))
            records[str(Path("grid") / "123p.png")] = f"{ARTWORK_VERSION}:{digest}"
            self.assertEqual(artwork_updates(home, grid, 123, records), ([], False))

    def test_untracked_artwork_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            grid = Path(directory)
            (grid / "123p.jpg").write_bytes(b"cover")
            (grid / "123_logo.png").write_bytes(b"custom")
            self.assertEqual(artwork_updates(grid, grid, 123, {}), (["hero", "landscape"], False))

    def test_only_owned_title_logo_is_marked_for_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            grid = Path(directory)
            logo = grid / "123_logo.png"
            logo.write_bytes(b"generated")
            digest = hashlib.sha256(b"generated").hexdigest()
            records = {logo.name: f"1:{digest}"}
            self.assertTrue(artwork_updates(grid, grid, 123, records)[1])
            custom = grid / "123_logo.webp"
            custom.touch()
            self.assertFalse(artwork_updates(grid, grid, 123, records)[1])
            custom.unlink()
            logo.write_bytes(b"custom")
            self.assertFalse(artwork_updates(grid, grid, 123, records)[1])

    def test_state_loads_legacy_and_versioned_artwork_records(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            store.path.parent.mkdir(parents=True)
            digest = hashlib.sha256(b"generated").hexdigest()
            records = {"grid/123p.png": digest, "grid/123.png": f"{ARTWORK_VERSION}:{digest}"}
            store.path.write_text(json.dumps({"artwork": {**records, "bad": "1:bad"}}), encoding="utf-8")
            self.assertEqual(store.load()["artwork"], records)

    def test_removed_shortcuts_delete_only_unchanged_generated_artwork_in_the_active_library(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            grid = home / "library/grid"
            other_grid = home / "other-library/grid"
            for parent in (grid, other_grid):
                parent.mkdir(parents=True)
            removed = grid / "123p.png"
            old = grid / "123_logo.png"
            custom = grid / "123_hero.png"
            active = grid / "456.png"
            other = other_grid / "123p.png"
            for path in (removed, old, custom, active, other):
                path.write_bytes(b"generated")
            digest = hashlib.sha256(b"generated").hexdigest()
            records = {str(path.relative_to(home)): digest for path in (old, custom, active, other)}
            records[str(removed.relative_to(home))] = f"{ARTWORK_VERSION}:{digest}"
            custom.write_bytes(b"custom")
            prune_artwork(home, grid, records, {456})
            self.assertFalse(removed.exists())
            self.assertFalse(old.exists())
            self.assertEqual(custom.read_bytes(), b"custom")
            self.assertEqual(set(records), {str(path.relative_to(home)) for path in (active, other)})
            self.assertTrue(active.exists() and other.exists())
