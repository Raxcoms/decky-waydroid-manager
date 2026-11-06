import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
import zipfile

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
        self.plugin._save_state = lambda home, state: setattr(self, "state", state)

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

    def test_stopped_android_keeps_menu_metadata_but_cannot_authorize_uninstall(self):
        self.plugin._run = lambda *args, **kwargs: "package:example.app"
        self.assertEqual(self.plugin._removable_packages(), {"example.app"})
        self.plugin._run = lambda *args, **kwargs: "WayDroid container is STOPPED"
        self.assertEqual(self.plugin._removable_packages(), {"example.app"})
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_NOT_RUNNING"):
            self.plugin._uninstall_package("example.app")

    def test_uninstall_checks_package_manager_success_before_removing_the_entry(self):
        entry = self.home / ".local/share/applications/waydroid.example.app.desktop"
        entry.parent.mkdir(parents=True)
        entry.write_text("app")
        result = "Failure [DELETE_FAILED_INTERNAL_ERROR]"
        def run(args, **kwargs):
            if args[3:7] == ["pm", "list", "packages", "-3"]:
                return "package:example.app"
            self.assertEqual(args, ["waydroid", "shell", "--", "pm", "uninstall", "example.app"])
            return result
        self.plugin._run = run
        with self.assertRaises(RuntimeError):
            self.plugin._uninstall_package("example.app")
        self.assertTrue(entry.exists())
        result = "Success"
        self.plugin._uninstall_package("example.app")
        self.assertFalse(entry.exists())

    def test_apk_install_rejects_android_failure_and_cleans_staging(self):
        apk = self.home / "app.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"manifest")
        self.plugin._initialized = lambda: True
        def run(args, **kwargs):
            if args == ["waydroid", "status"]:
                return "Session:\tRUNNING"
            self.assertEqual(args[:6], ["waydroid", "shell", "--", "pm", "install", "-r"])
            self.assertTrue(args[-1].startswith("/data/waydroid_tmp/"))
            return "Failure [INSTALL_FAILED_INVALID_APK]"
        self.plugin._run = run
        with self.assertRaisesRegex(RuntimeError, "INSTALL_FAILED_INVALID_APK"):
            self.plugin._install_package(str(apk))
        self.assertEqual(list((self.home / ".local/share/waydroid/data/waydroid_tmp").glob("decky-*")), [])

    def test_invalid_apk_archive_is_rejected_before_android_install(self):
        apk = self.home / "bad.apk"
        apk.write_text("not an APK")
        self.plugin._initialized = lambda: True
        self.plugin._run = lambda *args, **kwargs: "Session:\tRUNNING"
        with self.assertRaisesRegex(RuntimeError, "INVALID_PACKAGE_ARCHIVE"):
            self.plugin._install_package(str(apk))

    def test_stopped_session_is_reported_before_package_install(self):
        apk = self.home / "app.apk"
        apk.write_text("unused")
        self.plugin._initialized = lambda: True
        self.plugin._run = lambda *args, **kwargs: "Session:\tSTOPPED"
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_NOT_RUNNING"):
            self.plugin._install_package(str(apk))
