import importlib.util
import asyncio
import copy
from contextlib import nullcontext
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import zipfile

from steam_fixtures import write_shortcuts

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
        self.plugin._shortcuts_path = lambda home, account_id: self.path
        self.state = backend.StateStore.defaults()
        self.history["shortcuts"]["example.app"] = 123
        self.plugin._load_state = lambda home: self.state
        self.plugin._save_state = lambda home, state: setattr(self, "state", state)
        self.plugin._service_running = lambda: True

    @property
    def history(self):
        return backend.StateStore.account(self.state, 1)

    def tearDown(self):
        self.directory.cleanup()

    def test_app_list_uses_cached_package_metadata_and_ignores_invalid_exports(self):
        applications = self.home / ".local/share/applications"
        applications.mkdir(parents=True)
        (applications / "waydroid.example.app.desktop").write_text(
            "[Desktop Entry]\nName=Example\nExec=waydroid app launch example.app\n", encoding="utf-8")
        (applications / "waydroid.example.bad.desktop").write_bytes(b"\xff")
        self.state["removableApps"] = ["example.app"]
        self.plugin._initialized = lambda: True
        self.plugin._removable_packages = lambda: self.fail("Reading the app list started an Android command")
        apps = self.plugin._list_apps()
        self.assertEqual([app["package"] for app in apps], ["example.app"])
        self.assertTrue(apps[0]["removable"])

    def test_gapps_initialization_retries_only_when_ota_channels_are_missing(self):
        with patch.object(backend, "WAYDROID_DIR", self.home):
            command = ["waydroid", "init", "--system_type", "GAPPS"]
            (self.home / "waydroid.cfg").touch()

            def run(args, report):
                if args == command:
                    raise RuntimeError("ERROR: You must provide 'System OTA' and 'Vendor OTA' URLs.")
                self.assertEqual(args, [
                    *command,
                    "--system_channel", "https://ota.waydro.id/system",
                    "--vendor_channel", "https://ota.waydro.id/vendor",
                ])
                (self.home / "rootfs").mkdir()
                return ""

            with patch.object(backend, "run_init", side_effect=run):
                self.plugin._install_gapps()
            self.assertTrue(self.plugin._initialized())

    def test_gapps_initialization_preserves_other_cli_errors(self):
        self.plugin._initialized = lambda: False
        with patch.object(backend, "run_init", return_value="Image download failed") as run:
            with self.assertRaisesRegex(RuntimeError, "Image download failed"):
                self.plugin._install_gapps()
            run.assert_called_once()

    def test_image_setup_preserves_existing_android_language_preferences(self):
        (self.home / ".local/share/waydroid/data").mkdir(parents=True)
        self.plugin._initialized = lambda: True
        self.plugin._package_session = lambda progress: nullcontext()
        self.plugin._set_initial_locale = lambda *args: self.fail("Setup changed existing language preferences")
        self.plugin._wait_for_app_entries = lambda *args: None
        with patch.object(self.plugin, "_install_gapps") as initialize:
            self.assertTrue(self.plugin._initialize_image("pt-BR"))
            initialize.assert_not_called()

    def test_image_setup_waits_for_all_launchable_apps_to_be_exported(self):
        directory = self.home / ".local/share/applications"
        directory.mkdir(parents=True)
        (directory / "waydroid.example.first.desktop").touch()
        commands = []

        def run(command, *, timeout):
            commands.append(command)
            if len(commands) == 2:
                (directory / "waydroid.example.second.desktop").touch()
            return (
                "Name: First\npackageName: example.first\ncategories:\n\tandroid.intent.category.LAUNCHER\n"
                "Name: Service\npackageName: example.service\ncategories:\n\tandroid.intent.category.DEFAULT\n"
                "Name: Second\npackageName: example.second\ncategories:\n\tandroid.intent.category.LAUNCHER"
            )

        self.plugin._run = run
        with patch.object(backend.time, "sleep"):
            self.plugin._wait_for_app_entries("user", 1000, self.home)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][-3:], ["waydroid", "app", "list"])

    def test_install_confirmation_replies_require_current_target_token_and_one_boolean_decision(self):
        event, decision = threading.Event(), []
        self.plugin._install_confirmation = ("app.apk", "current", event, decision)
        for target, token, answer in (("other.apk", "current", True), ("app.apk", "stale", True), ("app.apk", "current", "true")):
            with self.assertRaisesRegex(RuntimeError, "VERIFICATION_UNAVAILABLE"):
                asyncio.run(self.plugin.confirm_package_install(target, token, answer))
        self.assertFalse(event.is_set())
        asyncio.run(self.plugin.confirm_package_install("app.apk", "current", False))
        self.assertEqual(decision, [False])
        self.assertTrue(event.is_set())
        with self.assertRaisesRegex(RuntimeError, "VERIFICATION_UNAVAILABLE"):
            asyncio.run(self.plugin.confirm_package_install("app.apk", "current", True))

    def test_app_shortcut_matches_wrapper_and_package(self):
        write_shortcuts(self.path, {"0": (0, {
            "exe": (1, str(self.plugin._launcher())), "appid": (2, 123),
            "appname": (1, "An App"),
            "LaunchOptions": (1, "/usr/libexec/armada/armada-game-launch %command% app example.app"),
        })})
        self.assertEqual(self.plugin._shortcut_ids(self.home, 1), {"example.app": 123})
        write_shortcuts(self.path, {})
        self.assertEqual(self.plugin._shortcut_ids(self.home, 1), {})

    def test_same_name_with_a_different_executable_is_not_owned(self):
        entry = self.home / ".local/share/applications/waydroid.example.app.desktop"
        entry.parent.mkdir(parents=True)
        entry.write_text("[Desktop Entry]\nName=An App\nExec=waydroid app launch example.app\n")
        write_shortcuts(self.path, {"0": (0, {
            "Exe": (1, "/usr/bin/unrelated"), "appid": (2, 123),
            "AppName": (1, "An App"), "LaunchOptions": (1, "app example.app"),
        })})
        self.assertEqual(self.plugin._shortcut_ids(self.home, 1), {})

    def test_new_shortcuts_use_only_the_bundled_launcher(self):
        shortcut = self.plugin._shortcut_details(1, "Example", "example.app")
        self.assertEqual(shortcut["exe"], str(self.plugin._launcher()))
        self.assertEqual(shortcut["launchOptions"], "app example.app")

    def test_shortcut_repairs_replace_only_default_names_and_exact_old_wrappers(self):
        self.plugin._desktop_entries = lambda **kwargs: [{"package": "example.app", "name": "Example"}]
        write_shortcuts(self.path, {
            "0": (0, {"Exe": (1, str(self.plugin._launcher())), "appid": (2, 123),
                      "AppName": (1, "waydroid-launcher"), "LaunchOptions": (1, "app example.app")}),
            "1": (0, {"Exe": (1, str(self.plugin._launcher())), "appid": (2, 456),
                      "AppName": (1, "Custom name"), "LaunchOptions": (1, "/usr/libexec/armada/armada-game-launch %command% full")}),
            "2": (0, {"Exe": (1, "/usr/bin/unrelated"), "appid": (2, 789),
                      "AppName": (1, "waydroid-launcher"), "LaunchOptions": (1, "app example.app")}),
        })
        self.assertEqual(self.plugin._legacy_shortcuts(1), [
            {"appId": 123, "name": "Example"}, {"appId": 456, "launchOptions": "full"},
        ])

    def test_third_party_packages_are_queried_with_waydroid_argument_separator(self):
        def run(args, **kwargs):
            if args[2:3] != ["--"]:
                raise RuntimeError("unrecognized arguments: -3")
            return "package:example.app\npackage:another.app\n"
        self.plugin._run = run
        self.assertEqual(self.plugin._removable_packages(), {"example.app", "another.app"})

    def test_offline_polling_never_activates_waydroid_dbus_service(self):
        self.plugin._service_running = lambda: False
        self.plugin._run = lambda *args, **kwargs: self.fail("Offline check contacted Waydroid")
        self.state["removableApps"] = ["example.app"]
        self.assertEqual(self.plugin._removable_packages(), {"example.app"})
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_NOT_RUNNING"):
            self.plugin._removable_packages(allow_cached=False)
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_NOT_RUNNING"):
            self.plugin._require_session()

    def test_native_shortcut_field_casing_and_changed_ids_are_resolved(self):
        write_shortcuts(self.path, {"0": (0, {
            "Exe": (1, str(self.plugin._launcher())), "appid": (2, 456),
            "AppName": (1, "Example"), "LaunchOptions": (1, "app example.app"),
        })})
        self.assertEqual(self.plugin._shortcut_ids(self.home, 1), {"example.app": 456})
        self.history.update({"autoAddApps": True, "observedApps": ["example.app"], "pendingApps": []})
        self.plugin._initialized = lambda: False
        self.plugin._desktop_entries = lambda **kwargs: []
        self.assertEqual(self.plugin._pending_auto_shortcuts(1, [456]), [])
        self.assertEqual(self.history["shortcuts"], {"example.app": 456})
        self.assertEqual(self.history["removedShortcuts"], [])

    def test_switching_accounts_does_not_reconcile_another_library(self):
        self.history.update({"autoAddApps": True, "removedShortcuts": ["example.hidden"]})
        other = backend.StateStore.account(self.state, 2)
        other["shortcuts"]["example.app"] = 456
        self.plugin._initialized = lambda: False
        self.plugin._pending_auto_shortcuts(2, [])
        self.assertEqual(other["removedShortcuts"], ["example.app"])
        self.assertEqual(self.history["shortcuts"], {"example.app": 123})
        self.assertEqual(self.history["removedShortcuts"], ["example.hidden"])
        self.assertTrue(self.history["autoAddApps"])

    def test_legacy_history_only_migrates_to_a_single_known_account(self):
        for accounts in ({1}, {1, 2}):
            state = backend.StateStore.defaults()
            state["legacy"] = {**backend.StateStore.shortcut_defaults(), "autoAddApps": True,
                               "removedShortcuts": ["example.hidden"]}
            with patch.object(backend, "known_accounts", return_value=accounts):
                history = self.plugin._account_state(self.home, state, 1)
            self.assertEqual(history["autoAddApps"], len(accounts) == 1)
            self.assertEqual(history["removedShortcuts"], ["example.hidden"] if len(accounts) == 1 else [])
            self.assertNotIn("legacy", state)

    def test_live_library_removal_stays_removed_until_uninstall_and_reinstall(self):
        self.history.update({"autoAddApps": True, "observedApps": ["example.app"], "pendingApps": []})
        self.plugin._initialized = lambda: False
        self.plugin._desktop_entries = lambda **kwargs: [
            {"name": "Example", "package": "example.app", "shortcutId": None, "iconPath": ""},
        ]
        self.assertEqual(self.plugin._pending_auto_shortcuts(1, []), [])
        self.assertEqual(self.history["shortcuts"], {})
        self.assertIn("example.app", self.history["removedShortcuts"])
        self.plugin._run = lambda args, **kwargs: "package:example.app" if "list" in args else "Success"
        self.plugin._remove_installed_package("example.app", 1)
        pending = self.plugin._pending_auto_shortcuts(1, [])
        self.assertEqual([item["key"] for item in pending], ["example.app"])

    def test_package_poll_does_not_overwrite_uninstall_history_cleanup(self):
        self.history.update({"observedApps": ["example.app"], "removedShortcuts": ["example.app"]})
        self.plugin._load_state = lambda home: copy.deepcopy(self.state)
        def run(*args, **kwargs):
            self.history.update({"observedApps": [], "removedShortcuts": [], "shortcuts": {}})
            return "package:another.app"
        self.plugin._run = run
        self.plugin._removable_packages()
        self.assertEqual(self.history["observedApps"], [])
        self.assertEqual(self.history["removedShortcuts"], [])
        self.assertEqual(self.history["shortcuts"], {})

    def test_stopped_android_keeps_menu_metadata_but_cannot_authorize_uninstall(self):
        self.plugin._run = lambda *args, **kwargs: "package:example.app"
        self.assertEqual(self.plugin._removable_packages(), {"example.app"})
        self.plugin._run = lambda *args, **kwargs: "WayDroid container is STOPPED"
        self.assertEqual(self.plugin._removable_packages(), {"example.app"})
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_NOT_RUNNING"):
            self.plugin._remove_installed_package("example.app", 1)

    def test_uninstall_checks_package_manager_success_before_removing_the_entry(self):
        write_shortcuts(self.path, {"0": (0, {
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
            self.plugin._remove_installed_package("example.app", 1)
        self.assertTrue(entry.exists())
        result = "Success"
        self.assertEqual(self.plugin._remove_installed_package("example.app", 1), 123)
        self.assertFalse(entry.exists())

    def test_uninstall_queues_each_accounts_shortcut_and_survives_backend_reload(self):
        paths = {1: self.home / "first.vdf", 2: self.home / "second.vdf"}
        for account, app_id in ((1, 123), (2, 456)):
            write_shortcuts(paths[account], {"0": (0, {
                "exe": (1, str(self.plugin._launcher())), "appid": (2, app_id),
                "LaunchOptions": (1, "app example.app"),
            })})
        self.plugin._shortcuts_path = lambda home, account_id: paths[account_id]
        self.plugin._load_state = lambda home: backend.StateStore(home).load()
        self.plugin._save_state = lambda home, state: backend.StateStore(home).save(state)
        self.plugin._run = lambda args, **kwargs: "package:example.app" if "list" in args else "Success"
        with patch.object(backend, "known_accounts", return_value={1, 2}), patch("waydroid_manager.state.os.chown", create=True):
            self.assertEqual(self.plugin._remove_installed_package("example.app", 1), 123)
            fresh = backend.Plugin()
            fresh._user = self.plugin._user
            fresh._shortcuts_path = self.plugin._shortcuts_path
            self.assertEqual(fresh._pending_shortcut_removals(1, None), {"ids": [], "waiting": True})
            self.assertEqual(fresh._pending_shortcut_removals(1, [123]), {"ids": [123], "waiting": False})
            self.assertEqual(fresh._pending_shortcut_removals(1, [123]), {"ids": [123], "waiting": False})
            self.assertEqual(fresh._pending_shortcut_removals(1, []), {"ids": [], "waiting": True})
            write_shortcuts(paths[1], {})
            self.assertEqual(fresh._pending_shortcut_removals(1, []), {"ids": [], "waiting": False})
            self.assertEqual(fresh._pending_shortcut_removals(2, [456]), {"ids": [456], "waiting": False})
            write_shortcuts(paths[2], {"0": (0, {"exe": (1, "/usr/bin/other"), "appid": (2, 456)})})
            self.assertEqual(fresh._pending_shortcut_removals(2, [456]), {"ids": [], "waiting": False})

    def test_reinstall_waits_for_old_shortcut_cleanup_before_automatic_add(self):
        self.history.update({"autoAddApps": True, "shortcuts": {}, "pendingRemovals": {"123": "example.app"}})
        self.plugin._initialized = lambda: False
        apps = [{"package": "example.app", "name": "Example", "iconPath": "", "shortcutId": 123}]
        self.plugin._desktop_entries = lambda **kwargs: apps
        self.assertEqual(self.plugin._pending_auto_shortcuts(1, [123]), [])
        self.assertEqual(self.history["pendingApps"], ["example.app"])
        self.assertEqual(self.plugin._pending_shortcut_removals(1, []), {"ids": [], "waiting": False})
        apps[0]["shortcutId"] = None
        self.assertEqual([item["key"] for item in self.plugin._pending_auto_shortcuts(1, [])], ["example.app"])

    def test_image_removal_preserves_queued_cleanup_after_resetting_preferences(self):
        self.history["autoAddApps"] = True
        self.history["pendingRemovals"]["234"] = "example.older"
        self.state["removableApps"] = ["example.app"]
        self.plugin._run = lambda *args, **kwargs: ""
        image = self.home.resolve() / "image"
        image.mkdir()
        with patch.object(backend, "WAYDROID_DIR", image), patch.object(backend, "require_unmounted"), patch.object(backend.decky, "logger", create=True):
            self.assertEqual(self.plugin._remove_image(1), [123])
        self.assertFalse(image.exists())
        self.assertFalse(self.history["autoAddApps"])
        self.assertEqual(self.state["removableApps"], [])
        self.assertEqual(self.history["pendingRemovals"], {"123": "example.app", "234": "example.older"})

    def test_apk_install_rejects_android_failure_and_cleans_staging(self):
        apk = self.home / "app.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"manifest")
        self.plugin._initialized = lambda: True
        self.plugin._package_session = lambda progress: nullcontext()
        (self.home / ".local/share/waydroid/data/local/tmp").mkdir(parents=True)
        def run(args, **kwargs):
            if args[4] == "install-create":
                return "Success: created install session [42]"
            if args[4] == "install-abandon":
                return "Success"
            self.assertEqual(args[4], "install-write")
            self.assertTrue(args[-1].startswith("/data/local/tmp/waydroid-manager-"))
            return "Failure [INSTALL_FAILED_INVALID_APK]"
        self.plugin._run = run
        with self.assertRaisesRegex(RuntimeError, "INSTALL_FAILED_INVALID_APK"):
            self.plugin._install_package(str(apk))
        self.assertEqual(list((self.home / ".local/share/waydroid/data/local/tmp").glob("waydroid-manager-*")), [])

    def test_invalid_apk_archive_is_rejected_before_android_install(self):
        apk = self.home / "bad.apk"
        apk.write_text("not an APK")
        self.plugin._initialized = lambda: True
        self.plugin._run = lambda *args, **kwargs: "Session:\tRUNNING"
        with self.assertRaisesRegex(RuntimeError, "INVALID_PACKAGE_ARCHIVE"):
            self.plugin._install_package(str(apk))

    def test_invalid_archive_is_rejected_without_starting_android(self):
        apk = self.home / "app.apk"
        apk.write_text("invalid")
        self.plugin._initialized = lambda: True
        self.plugin._package_session = lambda progress: self.fail("Invalid file started Android")
        with self.assertRaisesRegex(RuntimeError, "INVALID_PACKAGE_ARCHIVE"):
            self.plugin._install_package(str(apk))

    def test_successful_uninstall_forgets_manual_removal_and_reinstall_can_auto_add(self):
        self.history.update({
            "autoAddApps": True,
            "observedApps": ["example.app", "another.app"],
            "pendingApps": ["example.app"],
            "removedShortcuts": ["example.app"],
            "shortcuts": {"example.app": 123, "another.app": 456},
        })
        result = "Failure [DELETE_FAILED_INTERNAL_ERROR]"
        self.plugin._run = lambda args, **kwargs: "package:example.app" if "list" in args else result
        with self.assertRaises(RuntimeError):
            self.plugin._remove_installed_package("example.app", 1)
        self.assertIn("example.app", self.history["removedShortcuts"])
        self.assertIn("example.app", self.history["observedApps"])
        self.assertEqual(self.history["shortcuts"]["example.app"], 123)

        result = "Success"
        self.assertIsNone(self.plugin._remove_installed_package("example.app", 1))
        self.assertEqual(self.history["shortcuts"], {"another.app": 456})
        for key in ("observedApps", "pendingApps", "removedShortcuts", "removableApps"):
            self.assertNotIn("example.app", self.state[key] if key == "removableApps" else self.history[key])
        self.assertTrue(self.history["autoAddApps"])

        self.plugin._initialized = lambda: False
        self.plugin._desktop_entries = lambda **kwargs: [
            {"name": "Example", "package": "example.app", "shortcutId": None, "iconPath": ""},
            {"name": "Another", "package": "another.app", "shortcutId": 456, "iconPath": ""},
        ]
        pending = self.plugin._pending_auto_shortcuts(1)
        self.assertEqual([shortcut["key"] for shortcut in pending], ["example.app"])


class PackageSessionTests(unittest.TestCase):
    def setUp(self):
        self.plugin = backend.Plugin()
        self.plugin._initialized = lambda: True
        self.plugin._user = lambda: ("user", 1000, Path("/home/user"))
        self.socket = patch.object(backend, "steam_wayland_socket", return_value=Path("gamescope-primary"))
        self.socket.start()
        self.addCleanup(self.socket.stop)
        self.plugin._service_running = lambda: self.service_active
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
        if command == ["systemctl", "start", backend.SERVICE]:
            self.service_active = True
        if command == ["systemctl", "stop", backend.SERVICE]:
            self.service_active = False
        if command == ["waydroid", "status"]:
            return "Session: RUNNING" if self.session_running else "Session: STOPPED"
        if "getprop" in command:
            return self.booted
        if "show" in command:
            return self.unit_state
        return ""

    def remove(self, package, account_id):
        self.removed.append(package)
        return 123

    def test_running_session_is_reused_and_left_running(self):
        self.session_running = True
        self.assertEqual(self.plugin._uninstall_package("example.app"), 123)
        self.assertEqual(self.commands, [["waydroid", "status"], ["waydroid", "shell", "--", "getprop", "sys.boot_completed"]])
        self.assertEqual(self.removed, ["example.app"])

    def test_running_but_unready_session_is_waited_for_and_preserved(self):
        self.session_running = True
        self.booted = "0"
        def boot(*_):
            self.booted = "1"
        with patch.object(backend.time, "sleep", side_effect=boot):
            self.plugin._uninstall_package("example.app")
        self.assertEqual(self.removed, ["example.app"])
        self.assertFalse(any("stop" in command or "start" in command or "systemd-run" in command for command in self.commands))

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
        def fail(package, account_id):
            raise RuntimeError("DELETE_FAILED")
        self.plugin._remove_installed_package = fail
        with self.assertRaisesRegex(RuntimeError, "DELETE_FAILED"):
            self.plugin._uninstall_package("example.app")
        self.assertIn(["systemctl", "stop", backend.SERVICE], self.commands)
        self.assertTrue(any("stop" in command and "--user" in command for command in self.commands))

    def test_cleanup_timeout_preserves_the_original_operation_error(self):
        def run(command, **kwargs):
            if "stop" in command and "--user" in command:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            return self.run_command(command, **kwargs)

        self.plugin._run = run
        with patch.object(backend.decky, "logger", create=True) as logger:
            with self.assertRaisesRegex(RuntimeError, "INSTALL_FAILED"):
                with self.plugin._package_session():
                    raise RuntimeError("INSTALL_FAILED")
            logger.warning.assert_called_once()

    def test_slow_unit_status_still_allows_owned_session_cleanup(self):
        def run(command, **kwargs):
            if "show" in command:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            if "stop" in command and "--user" in command and kwargs["timeout"] <= 45:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            return self.run_command(command, **kwargs)

        self.plugin._run = run
        self.assertEqual(self.plugin._uninstall_package("example.app"), 123)
        self.assertTrue(any("stop" in command and "--user" in command for command in self.commands))

    def test_service_cleanup_still_runs_when_the_user_bus_is_unavailable(self):
        self.service_active = False

        def run(command, **kwargs):
            if "show" in command:
                raise RuntimeError("Failed to connect to user bus")
            return self.run_command(command, **kwargs)

        self.plugin._run = run
        with patch.object(backend.decky, "logger", create=True):
            with self.assertRaisesRegex(RuntimeError, "WAYDROID_CLEANUP_FAILED"):
                self.plugin._uninstall_package("example.app")
        self.assertIn(["systemctl", "stop", backend.SERVICE], self.commands)

    def test_failed_boot_does_not_attempt_removal(self):
        self.booted = "0"
        self.unit_state = "failed"
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_START_FAILED"):
            self.plugin._uninstall_package("example.app")
        self.assertEqual(self.removed, [])
        self.assertEqual(self.plugin._package_progress, {"operation": "uninstall", "target": "example.app", "stage": "failed"})

    def test_progress_tracks_boot_cleanup_and_library_handoff(self):
        stages = []
        original = self.plugin._set_package_progress
        def progress(operation, package, stage):
            stages.append(stage)
            original(operation, package, stage)
        self.plugin._set_package_progress = progress
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
        def remove(package, account_id):
            self.unit_state = "inactive"
            self.session_running = True
            return 123
        self.plugin._remove_installed_package = remove
        self.plugin._uninstall_package("example.app")
        self.assertFalse(any("stop" in command for command in self.commands))

    def test_install_boots_android_and_restores_owned_resources_on_success_and_failure(self):
        for result in ("Success", "Failure [INSTALL_FAILED_INVALID_APK]"):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                apk = home / "app.apk"
                with zipfile.ZipFile(apk, "w") as archive:
                    archive.writestr("AndroidManifest.xml", b"manifest")
                temp = home / ".local/share/waydroid/data/local/tmp"
                self.plugin._user = lambda: ("user", 1000, home)
                self.service_active = False
                self.commands.clear()
                def run(command, **kwargs):
                    if "getprop" in command:
                        temp.mkdir(parents=True, exist_ok=True)
                    if command[:4] == ["waydroid", "shell", "--", "pm"]:
                        self.commands.append(command)
                        self.assertEqual(len(list(temp.glob("waydroid-manager-*"))), 1)
                        if command[4] == "list":
                            return "package:example.app"
                        return {"install-create": "Success: created install session [42]", "install-write": "Success: streamed 100 bytes", "install-commit": result, "install-abandon": "Success"}[command[4]]
                    return self.run_command(command, **kwargs)
                self.plugin._run = run
                self.plugin._commit_package_install = lambda session, *args: run(["waydroid", "shell", "--", "pm", "install-commit", session])
                if result == "Success":
                    with patch("waydroid_manager.state.os.chown", create=True):
                        self.plugin._install_package(str(apk))
                    self.assertEqual(self.plugin._package_progress["stage"], "complete")
                    self.assertEqual(self.plugin._load_state(home)["removableApps"], ["example.app"])
                else:
                    with self.assertRaisesRegex(RuntimeError, "INSTALL_FAILED_INVALID_APK"):
                        self.plugin._install_package(str(apk))
                    self.assertEqual(self.plugin._package_progress["stage"], "failed")
                self.assertEqual(list(temp.glob("waydroid-manager-*")), [])
                self.assertIn(["systemctl", "stop", backend.SERVICE], self.commands)
