from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.steam import read_shortcuts, shortcuts_path, migrated_launch_options
from steam_fixtures import write_shortcuts


class SteamFilesTests(unittest.TestCase):
    def test_migration_replaces_only_the_exact_old_wrapper(self):
        self.assertEqual(migrated_launch_options("/usr/libexec/armada/armada-game-launch %command% app example.app"), "app example.app")
        self.assertEqual(migrated_launch_options("/usr/libexec/armada/armada-game-launch %command% full"), "full")
        for value in ("app example.app", "custom full", "/usr/libexec/armada/armada-game-launch %command% custom full"):
            self.assertIsNone(migrated_launch_options(value))

    def test_multiple_installations_are_not_selected_by_directory_order(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for root in (".local/share/Steam", ".var/app/com.valvesoftware.Steam/data/Steam"):
                (home / root / "userdata/1").mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "active Steam installation"):
                shortcuts_path(home)

    def test_active_account_wins_over_the_first_userdata_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / ".local/share/Steam"
            for account in ("1", "2"):
                (root / "userdata" / account / "config").mkdir(parents=True)
            (root / "config").mkdir()
            (root / "config/loginusers.vdf").write_text('"users" { "76561197960265729" { "MostRecent" "0" } "76561197960265730" { "PersonaName" "A {name}" "MostRecent" "1" } }')
            self.assertEqual(shortcuts_path(home), root / "userdata/2/config/shortcuts.vdf")

    def test_ambiguous_accounts_fail_instead_of_editing_someone_elses_library(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for account in ("1", "2"):
                (home / ".local/share/Steam/userdata" / account).mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "active Steam account"):
                shortcuts_path(home)

    def test_malformed_binary_files_raise_a_controlled_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shortcuts.vdf"
            for data in (b"\x00shortcuts\0\x02appid\0\x01", b"\x01shortcuts\0text\0\x08"):
                path.write_bytes(data)
                with self.assertRaises(RuntimeError):
                    read_shortcuts(path)
            write_shortcuts(path, {"0": (0, {"AppName": (1, "An app"), "appid": (2, -1)})})
            self.assertEqual(read_shortcuts(path)["0"][1]["appid"], (2, -1))
