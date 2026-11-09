import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_malformed_values_are_filtered_before_use(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            store.path.parent.mkdir(parents=True)
            store.path.write_text(json.dumps({"autoAddApps": "true", "observedApps": [{}, "example.app"], "shortcuts": {"bad": True, "app": 123}}))
            state = store.load()["legacy"]
            self.assertFalse(state["autoAddApps"])
            self.assertEqual(state["observedApps"], ["example.app"])
            self.assertEqual(state["shortcuts"], {"app": 123})

    def test_unchanged_state_does_not_rewrite_the_file(self):
        with tempfile.TemporaryDirectory() as directory, patch("waydroid_manager.state.os.chown", create=True):
            store = StateStore(Path(directory))
            state = store.load()
            store.account(state, 1)["autoAddApps"] = True
            store.save(state)
            inode = store.path.stat().st_ino
            with patch("waydroid_manager.state.tempfile.NamedTemporaryFile", side_effect=AssertionError("Unnecessary write")):
                store.save(state)
            self.assertEqual(store.path.stat().st_ino, inode)

    def test_default_state_stays_absent_after_full_removal(self):
        with tempfile.TemporaryDirectory() as directory, patch("waydroid_manager.state.os.chown", create=True):
            store = StateStore(Path(directory))
            state = store.load()
            store.save(state)
            self.assertFalse(store.path.parent.exists())

    def test_second_screen_preferences_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            store.path.parent.mkdir(parents=True)
            store.path.write_text(json.dumps({
                "secondScreen": {"container": True, "apps": {
                    "example.app": False, "bad/package": True, "other.app": "true",
                }},
            }))
            state = store.load()
            self.assertTrue(StateStore.second_screen_enabled(state))
            self.assertFalse(StateStore.second_screen_enabled(state, "example.app"))
            self.assertTrue(StateStore.second_screen_enabled(state, "other.app"))

            store.account(state, 1)["autoAddApps"] = True
            store.save(state)
            self.assertTrue(store.path.exists())
            store.clear()
            store.save(store.load())
            self.assertFalse(store.path.parent.exists())

    @unittest.skipIf(os.name == "nt", "Requires Unix symlinks")
    def test_state_directory_cannot_escape_the_user_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            outside = Path(directory) / "outside"
            home.mkdir()
            outside.mkdir()
            (home / ".config").symlink_to(outside, target_is_directory=True)
            store = StateStore(home)
            with self.assertRaisesRegex(RuntimeError, "outside the user home"):
                store.save(store.load())
            self.assertEqual(list(outside.iterdir()), [])
