import importlib.util
import copy
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
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

    def test_native_shortcut_field_casing_and_changed_ids_are_resolved(self):
        self.plugin._save_shortcuts(self.path, {"0": (0, {
            "Exe": (1, str(self.plugin._launcher())), "appid": (2, 456),
            "AppName": (1, "Example"), "LaunchOptions": (1, "app example.app"),
        })})
        self.assertEqual(self.plugin._shortcut_ids(self.home), {"example.app": 456})
        self.state.update({"autoAddApps": True, "observedApps": ["example.app"], "pendingApps": []})
        self.plugin._initialized = lambda: False
        self.plugin._desktop_entries = lambda: []
        self.assertEqual(self.plugin._pending_auto_shortcuts([456]), [])
        self.assertEqual(self.state["shortcuts"], {"example.app": 456})
        self.assertEqual(self.state["removedShortcuts"], [])

    def test_live_library_removal_stays_removed_until_uninstall_and_reinstall(self):
        self.state.update({"autoAddApps": True, "observedApps": ["example.app"], "pendingApps": []})
        self.plugin._initialized = lambda: False
        self.plugin._desktop_entries = lambda: [
            {"name": "Example", "package": "example.app", "shortcutId": None, "iconPath": ""},
        ]
        self.assertEqual(self.plugin._pending_auto_shortcuts([]), [])
        self.assertEqual(self.state["shortcuts"], {})
        self.assertIn("example.app", self.state["removedShortcuts"])
        self.plugin._run = lambda args, **kwargs: "package:example.app" if "list" in args else "Success"
        self.plugin._remove_installed_package("example.app")
        pending = self.plugin._pending_auto_shortcuts([])
        self.assertEqual([item["key"] for item in pending], ["example.app"])

    def test_package_poll_does_not_overwrite_uninstall_history_cleanup(self):
        self.state.update({"observedApps": ["example.app"], "removedShortcuts": ["example.app"]})
        self.plugin._load_state = lambda home: copy.deepcopy(self.state)
        def run(*args, **kwargs):
            self.state.update({"observedApps": [], "removedShortcuts": [], "shortcuts": {}})
            return "package:another.app"
        self.plugin._run = run
        self.plugin._removable_packages()
        self.assertEqual(self.state["observedApps"], [])
        self.assertEqual(self.state["removedShortcuts"], [])
        self.assertEqual(self.state["shortcuts"], {})

    def test_stopped_android_keeps_menu_metadata_but_cannot_authorize_uninstall(self):
        self.plugin._run = lambda *args, **kwargs: "package:example.app"
        self.assertEqual(self.plugin._removable_packages(), {"example.app"})
        self.plugin._run = lambda *args, **kwargs: "WayDroid container is STOPPED"
        self.assertEqual(self.plugin._removable_packages(), {"example.app"})
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_NOT_RUNNING"):
            self.plugin._remove_installed_package("example.app")

    def test_uninstall_checks_package_manager_success_before_removing_the_entry(self):
        self.plugin._save_shortcuts(self.path, {"0": (0, {
            "exe": (1, str(self.plugin._launcher())), "appid": (2, 123),
            "LaunchOptions": (1, "app example.app"),
        })})
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
            self.plugin._remove_installed_package("example.app")
        self.assertTrue(entry.exists())
        result = "Success"
        self.assertEqual(self.plugin._remove_installed_package("example.app"), 123)
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

    def test_successful_uninstall_forgets_manual_removal_and_reinstall_can_auto_add(self):
        self.state.update({
            "autoAddApps": True,
            "observedApps": ["example.app", "another.app"],
            "pendingApps": ["example.app"],
            "removedShortcuts": ["example.app"],
            "shortcuts": {"example.app": 123, "another.app": 456},
        })
        result = "Failure [DELETE_FAILED_INTERNAL_ERROR]"
        self.plugin._run = lambda args, **kwargs: "package:example.app" if "list" in args else result
        with self.assertRaises(RuntimeError):
            self.plugin._remove_installed_package("example.app")
        self.assertIn("example.app", self.state["removedShortcuts"])
        self.assertIn("example.app", self.state["observedApps"])
        self.assertEqual(self.state["shortcuts"]["example.app"], 123)

        result = "Success"
        self.assertIsNone(self.plugin._remove_installed_package("example.app"))
        self.assertEqual(self.state["shortcuts"], {"another.app": 456})
        for key in ("observedApps", "pendingApps", "removedShortcuts", "removableApps"):
            self.assertNotIn("example.app", self.state[key])
        self.assertTrue(self.state["autoAddApps"])

        self.plugin._initialized = lambda: False
        self.plugin._desktop_entries = lambda: [
            {"name": "Example", "package": "example.app", "shortcutId": None, "iconPath": ""},
            {"name": "Another", "package": "another.app", "shortcutId": 456, "iconPath": ""},
        ]
        pending = self.plugin._pending_auto_shortcuts()
        self.assertEqual([shortcut["key"] for shortcut in pending], ["example.app"])


class PackageSessionTests(unittest.TestCase):
    def setUp(self):
        self.plugin = backend.Plugin()
        self.plugin._initialized = lambda: True
        self.plugin._user = lambda: ("user", 1000, Path("/home/user"))
        self.plugin._steam_graphics_environment = lambda uid: {
            "GAMESCOPE_WAYLAND_DISPLAY": "gamescope-primary", "WAYLAND_DISPLAY": "other-display",
        }
        self.plugin._service_state = lambda state: self.service_active
        self.service_active = True
        self.session_running = False
        self.unit_state = "active"
        self.booted = "1"
        self.commands = []
        self.removed = []
        self.plugin._run = self.run_command
        self.plugin._remove_installed_package = self.remove

    def run_command(self, command, **kwargs):
        self.commands.append(command)
        if command == ["waydroid", "status"]:
            return "Session: RUNNING" if self.session_running else "Session: STOPPED"
        if "getprop" in command:
            return self.booted
        if "show" in command:
            return self.unit_state
        return ""

    def remove(self, package):
        self.removed.append(package)
        return 123

    def test_running_session_is_reused_and_left_running(self):
        self.session_running = True
        self.assertEqual(self.plugin._uninstall_package("example.app"), 123)
        self.assertEqual(self.commands, [["waydroid", "status"]])
        self.assertEqual(self.removed, ["example.app"])

    def test_stopped_session_boots_hidden_on_steam_socket_and_stops_only_owned_unit(self):
        self.assertEqual(self.plugin._uninstall_package("example.app"), 123)
        start = next(command for command in self.commands if "systemd-run" in command)
        stop = next(command for command in self.commands if "--user" in command and "stop" in command)
        unit = next(value.removeprefix("--unit=") for value in start if value.startswith("--unit="))
        self.assertIn("WAYLAND_DISPLAY=gamescope-primary", start)
        self.assertEqual(start[-3:], ["waydroid", "session", "start"])
        self.assertEqual(stop[-2:], ["stop", unit])
        self.assertNotIn(["systemctl", "stop", backend.SERVICE], self.commands)
        self.assertFalse(any("show-full-ui" in command or "launch" in command for command in self.commands))

    def test_service_started_for_removal_is_restored_after_failure(self):
        self.service_active = False
        def fail(package):
            raise RuntimeError("DELETE_FAILED")
        self.plugin._remove_installed_package = fail
        with self.assertRaisesRegex(RuntimeError, "DELETE_FAILED"):
            self.plugin._uninstall_package("example.app")
        self.assertIn(["systemctl", "stop", backend.SERVICE], self.commands)
        self.assertTrue(any("stop" in command and "--user" in command for command in self.commands))

    def test_failed_boot_does_not_attempt_removal(self):
        self.booted = "0"
        self.unit_state = "failed"
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_START_FAILED"):
            self.plugin._uninstall_package("example.app")
        self.assertEqual(self.removed, [])
        self.assertEqual(self.plugin._uninstall_progress, {"package": "example.app", "stage": "failed"})

    def test_progress_tracks_boot_cleanup_and_library_handoff(self):
        stages = []
        original = self.plugin._set_uninstall_progress
        def progress(package, stage):
            stages.append(stage)
            original(package, stage)
        self.plugin._set_uninstall_progress = progress
        self.plugin._uninstall_package("example.app")
        self.assertEqual(stages, ["preparing", "starting", "booting", "cleaning", "library"])

    def test_timed_out_boot_cleans_up_without_removal(self):
        self.service_active = False
        with patch.object(backend.time, "monotonic", side_effect=[0, 181]):
            with self.assertRaisesRegex(RuntimeError, "WAYDROID_START_FAILED"):
                self.plugin._uninstall_package("example.app")
        self.assertEqual(self.removed, [])
        self.assertIn(["systemctl", "stop", backend.SERVICE], self.commands)

    def test_replacement_session_keeps_service_running(self):
        self.service_active = False
        def remove(package):
            self.unit_state = "inactive"
            self.session_running = True
            return 123
        self.plugin._remove_installed_package = remove
        self.plugin._uninstall_package("example.app")
        self.assertFalse(any("stop" in command for command in self.commands))
