import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py_modules"))
if os.name == "nt":
    sys.modules.setdefault("pwd", types.SimpleNamespace())
sys.modules.setdefault("decky", types.SimpleNamespace(DECKY_PLUGIN_DIR=str(ROOT)))
spec = importlib.util.spec_from_file_location("waydroid_backend", ROOT / "main.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.home = Path(self.directory.name)
        self.plugin = backend.Plugin()
        self.plugin._user = lambda: ("user", 1000, self.home)
        self.path = self.home / "shortcuts.vdf"
        self.plugin._shortcuts_path = lambda home: self.path
        self.state = {"shortcuts": {"example.app": 123}, "removedShortcuts": []}
        self.plugin._load_state = lambda home: self.state

    def tearDown(self):
        self.directory.cleanup()

    def test_app_shortcut_matches_wrapper_and_package(self):
        self.plugin._save_shortcuts(self.path, {"0": (0, {
            "exe": (1, str(self.plugin._launcher())), "appid": (2, 123),
            "appname": (1, "An App"),
            "LaunchOptions": (1, "/usr/libexec/armada/armada-game-launch %command% app example.app"),
        })})
        self.assertEqual(self.plugin._shortcut_ids(self.home), {"example.app": 123})
        self.plugin._save_shortcuts(self.path, {})
        self.assertEqual(self.plugin._shortcut_ids(self.home), {})

    def test_third_party_packages_are_queried_with_waydroid_argument_separator(self):
        def run(args, **kwargs):
            if args[2:3] != ["--"]:
                raise RuntimeError("unrecognized arguments: -3")
            return "package:example.app\npackage:another.app\n"
        self.plugin._run = run
        self.assertEqual(self.plugin._removable_packages(), {"example.app", "another.app"})
