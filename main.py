import base64
import asyncio
import json
import os
import pwd
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

import decky
from waydroid_manager.apps import PACKAGE_RE, app_exports
from waydroid_manager.frame_limit import FrameLimiter
from waydroid_manager.proc import clean_env, process_identity, steam_session, steam_wayland_socket
from waydroid_manager.artwork import ARTWORK_TYPES, ARTWORK_VERSION, artwork_attached, artwork_filename, artwork_updates, prune_artwork
from waydroid_manager.metrics import GpuMetrics
from waydroid_manager.packages import apk_members, stage_apks, install_apks, check_result
from waydroid_manager.verification import InstallCancelled, InstallVerification, commit_install
from waydroid_manager.steam import known_accounts, read_shortcuts, shortcuts_path, shortcut_key, shortcut_owners, migrated_launch_options
from waydroid_manager.container import CONFIG_DIR, SERVICE, container_identity, container_pid, registered_guest, session_uses_socket, vendor_overlay_warning
from waydroid_manager.guest import GUEST_STARTING, LaunchPolicy, android_user_ready, keep_package_guest_running, run_dex, set_media_volume_max
from waydroid_manager.image import launcher_packages, owned_directory, require_unmounted, require_unredirected, run_init
from waydroid_manager.control import Launch, ServiceControl, control_path
from waydroid_manager.state import StateStore
from waydroid_manager.user_files import open_as_user, run_as_user


WAYDROID_DIR = CONFIG_DIR
MAX_ICON_BYTES = 2 * 1024 * 1024
WAYDROID_SHORTCUT_KEY = "waydroid"


class Plugin:
    INPUT_SYNC_UNIT = "waydroid-manager-input-sync.service"

    def __init__(self):
        self._state_lock = threading.RLock()
        self._package_progress: dict[str, str] = {}
        self._image_progress: dict[str, str | int | None] | None = None
        self._install_confirmation = None
        self._control = None

    @contextmanager
    def _edit_state(self, home: Path):
        with self._state_lock:
            state = self._load_state(home)
            yield state
            self._save_state(home, state)

    def _run(self, command: list[str], timeout: int = 30, *, stdin=None) -> str:
        result = subprocess.run(
            command,
            env=clean_env(),
            stdin=stdin,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stdout.strip() or f"{' '.join(command)} failed")
        return result.stdout.strip()

    def _user(self) -> tuple[str, int, Path]:
        user_home = getattr(decky, "DECKY_USER_HOME", None)
        if user_home:
            home = Path(user_home).resolve()
            if home.is_dir():
                account = pwd.getpwuid(home.stat().st_uid)
                return account.pw_name, account.pw_uid, home

        accounts = [account for account in pwd.getpwall() if account.pw_uid >= 1000 and Path(account.pw_dir).is_dir()]
        if len(accounts) == 1:
            account = accounts[0]
            return account.pw_name, account.pw_uid, Path(account.pw_dir).resolve()
        raise RuntimeError("Could not find the Decky user")

    def _initialized(self) -> bool:
        return (WAYDROID_DIR / "waydroid.cfg").is_file() and (WAYDROID_DIR / "rootfs").is_dir()

    def _service_running(self) -> bool:
        return subprocess.run(
            ["systemctl", "is-active", SERVICE],
            env=clean_env(),
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0

    def _launcher(self) -> Path:
        path = Path(decky.DECKY_PLUGIN_DIR) / "bin" / "waydroid-launcher"
        if not path.is_file():
            raise RuntimeError("The bundled Waydroid launcher is missing")
        return path

    def _input_sync(self) -> Path:
        path = Path(decky.DECKY_PLUGIN_DIR) / "bin" / "waydroid-input-sync"
        if not path.is_file():
            raise RuntimeError("The bundled Waydroid input synchronizer is missing")
        return path

    def _start_input_sync(self, launch: Launch) -> None:
        subprocess.run(
            ["systemctl", "stop", self.INPUT_SYNC_UNIT],
            env=clean_env(), timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self._run([
            "systemd-run", "--quiet", "--no-block", "--collect",
            "--unit=waydroid-manager-input-sync",
            str(self._input_sync()), str(launch.process[0]), launch.process[1], str(launch.display),
        ])

    async def _prepare_launch(self, launch: Launch) -> None:
        try:
            await asyncio.to_thread(self._start_input_sync, launch)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            decky.logger.warning("Waydroid controller bridge unavailable: %s", error)

    async def _launch_policy(self, launch: Launch, mode: str) -> None:
        await asyncio.to_thread(self._prepare_guest_presentation, launch, mode)

    async def _release_launch(self, launch: Launch) -> None:
        await asyncio.to_thread(self._stop_launch, launch)

    def _stop_launch(self, launch: Launch) -> None:
        user, uid, home = self._user()
        try:
            if session_uses_socket(launch.display):
                try:
                    self._policy.restore()
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    decky.logger.warning("Could not restore Android display policy: %s", error)
                if session_uses_socket(launch.display):
                    self._run(["busctl", "--system", "--timeout=12s", "call", "id.waydro.Container",
                               "/ContainerManager", "id.waydro.ContainerManager", "Stop", "b", "true"], timeout=15)
        finally:
            command = [*self._user_command(user, uid, home), "systemctl", "--user"]
            try:
                self._run([*command, "is-active", "--quiet", launch.unit], timeout=5)
            except RuntimeError:
                pass
            else:
                self._run([*command, "stop", "--no-block", launch.unit], timeout=5)

    def _prepare_guest_presentation(self, launch: Launch, mode: str) -> None:
        if not session_uses_socket(launch.display):
            raise RuntimeError("Waydroid launch is no longer active")
        if not android_user_ready(self._run):
            raise RuntimeError(GUEST_STARTING)
        self._policy.save(mode)

    def _stop_input_sync(self) -> None:
        subprocess.run(
            ["systemctl", "stop", self.INPUT_SYNC_UNIT],
            env=clean_env(), timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    @staticmethod
    def _data_home(home: Path, uid: int) -> Path:
        session = steam_session(uid)
        return session.data_home if session and session.data_home else home / ".local/share"

    def _icon_data_uri(self, value: str, data_home: Path) -> str:
        try:
            icon = Path(value).resolve(strict=True)
            icon.relative_to(data_home.resolve() / "waydroid/data/icons")
            if icon.suffix.lower() != ".png" or not icon.is_file():
                return ""
            with icon.open("rb") as file:
                content = file.read(MAX_ICON_BYTES + 1)
        except (OSError, ValueError):
            return ""
        if len(content) > MAX_ICON_BYTES:
            return ""
        return "data:image/png;base64," + base64.b64encode(content).decode("ascii")

    def _load_state(self, home: Path) -> dict[str, Any]:
        if os.geteuid() == home.stat().st_uid:
            return StateStore(home).load()
        return json.loads(self._user_files(home, "load"))

    def _save_state(self, home: Path, state: dict[str, Any]) -> None:
        if os.geteuid() == home.stat().st_uid:
            StateStore(home).save(state)
        else:
            self._user_files(home, "save", payload=json.dumps(state).encode())

    @staticmethod
    def _user_files_helper() -> Path:
        return Path(decky.DECKY_PLUGIN_DIR) / "bin/waydroid-user-files"

    def _user_files(self, home: Path, action: str, *args: str, payload: bytes | None = None) -> bytes:
        return run_as_user(self._user_files_helper(), home, action, *args, payload=payload)

    def _account_state(self, home: Path, state: dict, account_id: int) -> dict:
        legacy = state.pop("legacy", None)
        if legacy is not None and not state["accounts"]:
            try:
                if known_accounts(home) == {account_id}:
                    state["accounts"][str(account_id)] = legacy
            except (OSError, ValueError, RuntimeError):
                pass
        return StateStore.account(state, account_id)

    def _shortcut_ids(self, home: Path, account_id: int | None, history: dict | None = None) -> dict[str, int]:
        if account_id is None:
            return {}
        try:
            path = self._shortcuts_path(home, account_id)
        except (OSError, RuntimeError, ValueError):
            return {}
        if history is None:
            history = self._account_state(home, self._load_state(home), account_id)
        removed = set(history["removedShortcuts"])
        try:
            owners = shortcut_owners(path, self._launcher())
        except (OSError, RuntimeError, ValueError):
            return history["shortcuts"].copy()
        return {key: app_id for app_id, key in owners.items() if key is not None and key not in removed}

    def _removable_packages(self, allow_cached: bool = True) -> set[str]:
        _, _, home = self._user()
        if not self._service_running():
            if not allow_cached:
                raise RuntimeError("WAYDROID_NOT_RUNNING")
            return set(self._load_state(home).get("removableApps", []))
        try:
            output = self._run(["waydroid", "shell", "--", "pm", "list", "packages", "-3"], timeout=10)
        except (RuntimeError, subprocess.TimeoutExpired):
            output = "unavailable"
        packages = {
            line.removeprefix("package:")
            for line in output.splitlines()
            if line.startswith("package:") and PACKAGE_RE.fullmatch(line.removeprefix("package:"))
        }
        if packages or not output:
            with self._edit_state(home) as state:
                state["removableApps"] = sorted(packages)
            return packages
        if not allow_cached:
            raise RuntimeError("WAYDROID_NOT_RUNNING")
        return set(self._load_state(home).get("removableApps", []))

    def _desktop_entries(self, removable_packages: set[str] | None = None, *, account_id: int | None = None,
                         package: str | None = None, include_icons: bool = False) -> list[dict[str, Any]]:
        _, uid, home = self._user()
        shortcut_ids = self._shortcut_ids(home, account_id)
        data_home = self._data_home(home, uid)
        removable = removable_packages or set()
        apps = [{
            "name": app.name,
            "package": app.package,
            "icon": self._icon_data_uri(app.icon, data_home) if include_icons else "",
            "iconPath": app.icon,
            "shortcutId": shortcut_ids.get(app.package),
            "removable": app.package in removable,
        } for app in app_exports(home, package, data_home=data_home)]
        return sorted(apps, key=lambda app: app["name"].casefold())

    def _shortcuts_path(self, home: Path, account_id: int) -> Path:
        if type(account_id) is not int or not 0 < account_id <= 0xFFFFFFFF:
            raise RuntimeError("Invalid Steam account ID")
        return shortcuts_path(home, account_id)

    def _status(self, account_id: int | None) -> dict[str, Any]:
        _, uid, home = self._user()
        history = self._account_state(home, self._load_state(home), account_id) if account_id is not None else StateStore.shortcut_defaults()
        shortcut_ids = self._shortcut_ids(home, account_id, history)
        return {
            "initialized": self._initialized(),
            "hasAppEntries": next(app_exports(home, data_home=self._data_home(home, uid)), None) is not None,
            "serviceRunning": self._service_running(),
            "sessionAvailable": steam_wayland_socket(uid) is not None,
            "autoAddApps": history["autoAddApps"],
            "accountId": account_id,
            "userHome": str(home),
            "waydroidShortcutId": shortcut_ids.get(WAYDROID_SHORTCUT_KEY),
        }

    async def get_status(self, account_id: int | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._status, account_id)

    def _list_apps(self, account_id: int | None = None) -> list[dict[str, Any]]:
        if not self._initialized():
            return []
        _, _, home = self._user()
        removable = set(self._load_state(home).get("removableApps", []))
        return self._desktop_entries(removable, account_id=account_id, include_icons=True)

    async def list_apps(self, account_id: int | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_apps, account_id)

    def _shortcut_details(self, account_id: int, name: str, package: str | None = None, icon: str = "") -> dict[str, Any]:
        _, _, home = self._user()
        return {
            "name": name,
            "exe": str(self._launcher()),
            "startDir": str(home),
            "launchOptions": "full" if package is None else f"app {package}",
            "icon": icon,
            "key": WAYDROID_SHORTCUT_KEY if package is None else package,
            "accountId": account_id,
        }

    def _validate_shortcut_key(self, key: str) -> None:
        if key == WAYDROID_SHORTCUT_KEY:
            return
        if not PACKAGE_RE.fullmatch(key):
            raise RuntimeError("Invalid Android package name")

    async def record_shortcut(self, account_id: int, key: str, app_id: int) -> None:
        self._validate_shortcut_key(key)
        if type(app_id) is not int or not 0 < app_id <= 0xFFFFFFFF:
            raise RuntimeError("Steam did not return a valid shortcut ID")
        _, _, home = self._user()
        self._shortcuts_path(home, account_id)
        with self._edit_state(home) as state:
            history = self._account_state(home, state, account_id)
            if key in history["pendingRemovals"].values():
                raise RuntimeError("STEAM_SHORTCUT_CLEANUP_PENDING")
            data_home = self._data_home(home, home.stat().st_uid)
            if key != WAYDROID_SHORTCUT_KEY and next(app_exports(home, key, data_home=data_home), None) is None:
                raise RuntimeError("Android app is no longer installed")
            history["shortcuts"][key] = app_id
            history["removedShortcuts"] = [item for item in history["removedShortcuts"] if item != key]
            history["pendingApps"] = [item for item in history["pendingApps"] if item != key]

    async def remove_shortcut_record(self, account_id: int, key: str) -> None:
        self._validate_shortcut_key(key)
        _, _, home = self._user()
        self._shortcuts_path(home, account_id)
        with self._edit_state(home) as state:
            history = self._account_state(home, state, account_id)
            history["shortcuts"].pop(key, None)
            history["pendingApps"] = [item for item in history["pendingApps"] if item != key]
            if key not in history["removedShortcuts"]:
                history["removedShortcuts"].append(key)

    async def set_auto_add_apps(self, account_id: int, enabled: bool) -> None:
        _, _, home = self._user()
        self._shortcuts_path(home, account_id)
        with self._edit_state(home) as state:
            history = self._account_state(home, state, account_id)
            history["autoAddApps"] = enabled
            if enabled:
                history["observedApps"] = sorted({*history["observedApps"], *(app["package"] for app in self._desktop_entries())})

    def _pending_auto_shortcuts(self, account_id: int, live_ids: list[int] | None = None) -> list[dict[str, Any]]:
        if self._initialized() and container_pid() is not None:
            self._removable_packages()
        _, _, home = self._user()
        path = self._shortcuts_path(home, account_id)
        with self._state_lock:
            return self._update_auto_shortcuts(home, account_id, path, live_ids)

    def _update_auto_shortcuts(self, home: Path, account_id: int, path: Path, live_ids: list[int] | None) -> list[dict[str, Any]]:
        state = self._load_state(home)
        history = self._account_state(home, state, account_id)
        if live_ids is not None:
            ids = set(live_ids)
            if state.get("artwork"):
                if os.geteuid() == home.stat().st_uid:
                    prune_artwork(home, path.parent / "grid", state["artwork"], ids)
                else:
                    state["artwork"] = json.loads(self._user_files(
                        home, "prune-artwork", str(path.parent / "grid"),
                        payload=json.dumps([state["artwork"], sorted(ids)]).encode(),
                    ))
            discovered = self._shortcut_ids(home, account_id, history)
            for key, app_id in list(history["shortcuts"].items()):
                if app_id in ids:
                    continue
                replacement = discovered.get(key)
                if replacement in ids:
                    history["shortcuts"][key] = replacement
                else:
                    history["shortcuts"].pop(key)
                    if key not in history["removedShortcuts"]:
                        history["removedShortcuts"].append(key)
                    history["pendingApps"] = [item for item in history["pendingApps"] if item != key]
        if not history["autoAddApps"]:
            self._save_state(home, state)
            return []

        apps = self._desktop_entries(account_id=account_id)
        installed = {app["package"]: app for app in apps}
        observed = set(history["observedApps"])
        removed = set(history["removedShortcuts"])
        recorded = set(history["shortcuts"])
        pending = set(history["pendingApps"])
        removing = set(history["pendingRemovals"].values())
        missing = {package for package, app in installed.items() if not app["shortcutId"] or package in removing}
        pending.update(missing - observed - removed - recorded)
        pending &= missing
        history["observedApps"] = sorted(observed | set(installed))
        history["pendingApps"] = sorted(pending)
        self._save_state(home, state)
        return [
            self._shortcut_details(account_id, app["name"], package, app["iconPath"])
            for package, app in installed.items()
            if package in pending - removing
        ]

    async def pending_auto_shortcuts(self, account_id: int, live_ids: list[int] | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._pending_auto_shortcuts, account_id, live_ids)

    def _pending_shortcut_removals(self, account_id: int, live_ids: list[int] | None) -> dict[str, Any]:
        _, _, home = self._user()
        path = self._shortcuts_path(home, account_id)
        with self._edit_state(home) as state:
            history = self._account_state(home, state, account_id)
            queued = history["pendingRemovals"]
            if live_ids is None or not queued:
                return {"ids": [], "waiting": bool(queued)}
            owners = shortcut_owners(path, self._launcher())
            live = set(live_ids)
            ready = []
            for value, key in list(queued.items()):
                app_id = int(value)
                if app_id in owners and owners[app_id] != key:
                    queued.pop(value)
                elif app_id not in owners and app_id not in live:
                    queued.pop(value)
                elif owners.get(app_id) == key:
                    ready.append(app_id)
            return {"ids": ready, "waiting": len(queued) > len(ready)}

    async def pending_shortcut_removals(self, account_id: int, live_ids: list[int] | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._pending_shortcut_removals, account_id, live_ids)

    def _legacy_shortcuts(self, account_id: int) -> list[dict[str, Any]]:
        _, _, home = self._user()
        result = []
        names = {app["package"]: app["name"] for app in self._desktop_entries()}
        names[WAYDROID_SHORTCUT_KEY] = "Waydroid"
        for _, (_, entry) in read_shortcuts(self._shortcuts_path(home, account_id)).items():
            entry = {key.casefold(): value for key, value in entry.items()}
            exe = str(entry.get("exe", (1, ""))[1]).strip('"')
            existing_options = str(entry.get("launchoptions", (1, ""))[1])
            options = migrated_launch_options(existing_options)
            app_id = entry.get("appid", (2, 0))[1]
            key = shortcut_key(existing_options)
            if Path(exe).resolve() != self._launcher().resolve() or not key or not isinstance(app_id, int) or not app_id:
                continue
            update: dict[str, Any] = {"appId": app_id & 0xFFFFFFFF}
            if options:
                update["launchOptions"] = options
            if entry.get("appname", (1, ""))[1] == self._launcher().name and key in names:
                update["name"] = names[key]
            if len(update) > 1:
                result.append(update)
        return result

    async def legacy_shortcuts(self, account_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._legacy_shortcuts, account_id)

    def _require_shortcut_available(self, account_id: int, key: str) -> None:
        _, _, home = self._user()
        self._shortcuts_path(home, account_id)
        history = self._account_state(home, self._load_state(home), account_id)
        if key in history["pendingRemovals"].values():
            raise RuntimeError("STEAM_SHORTCUT_CLEANUP_PENDING")

    async def get_waydroid_shortcut(self, account_id: int) -> dict[str, Any]:
        self._require_shortcut_available(account_id, WAYDROID_SHORTCUT_KEY)
        return self._shortcut_details(account_id, "Waydroid")

    async def get_app_shortcut(self, account_id: int, package: str) -> dict[str, Any]:
        if not PACKAGE_RE.fullmatch(package):
            raise RuntimeError("Invalid Android package name")
        app = next(iter(self._desktop_entries(package=package)), None)
        if not app:
            raise RuntimeError("Android app is no longer installed")
        self._require_shortcut_available(account_id, package)
        return self._shortcut_details(account_id, app["name"], package, app["iconPath"])

    def _pending_shortcut_artwork(self, account_id: int) -> list[dict[str, Any]]:
        _, _, home = self._user()
        try:
            grid = self._shortcuts_path(home, account_id).parent / "grid"
        except RuntimeError:
            return []
        records = self._load_state(home)["artwork"]
        return [{"key": key, "appId": app_id} for key, app_id in self._shortcut_ids(home, account_id).items()
                if any(artwork_updates(home, grid, app_id, records))]

    async def pending_shortcut_artwork(self, account_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._pending_shortcut_artwork, account_id)

    def _shortcut_artwork(self, account_id: int, key: str, app_id: int) -> dict[str, Any]:
        self._validate_shortcut_key(key)
        _, _, home = self._user()
        if self._shortcut_ids(home, account_id).get(key) != app_id:
            raise RuntimeError("The Steam shortcut no longer exists")
        grid = (self._shortcuts_path(home, account_id).parent / "grid").resolve()
        if not grid.is_relative_to(home):
            raise RuntimeError("The Steam artwork directory is outside the user home")
        roles, clear_logo = artwork_updates(home, grid, app_id, self._load_state(home)["artwork"])
        app = next(iter(self._desktop_entries(package=key, include_icons=True)), None) if key != WAYDROID_SHORTCUT_KEY else None
        available = app is not None or key == WAYDROID_SHORTCUT_KEY
        return {
            "roles": roles if available else [], "clearLogo": clear_logo,
            "ready": available and not roles and artwork_attached(grid, app_id),
            "name": app["name"] if app else "Waydroid", "icon": app["icon"] if app else "",
        }

    async def get_shortcut_artwork(self, account_id: int, key: str, app_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._shortcut_artwork, account_id, key, app_id)

    async def record_shortcut_artwork(self, account_id: int, app_id: int, role: str, digest: str, version: int = 0) -> None:
        if (type(app_id) is not int or not 0 < app_id <= 0xFFFFFFFF
                or role not in {*ARTWORK_TYPES, "logoPosition"} or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or type(version) is not int or not 0 <= version <= ARTWORK_VERSION):
            raise RuntimeError("Invalid Steam artwork record")
        _, _, home = self._user()
        grid = (self._shortcuts_path(home, account_id).parent / "grid").resolve()
        if not grid.is_relative_to(home):
            raise RuntimeError("The Steam artwork directory is outside the user home")
        with self._edit_state(home) as state:
            if app_id in self._shortcut_ids(home, account_id).values():
                path = grid / artwork_filename(app_id, role)
                state["artwork"][str(path.relative_to(home))] = f"{version}:{digest}" if version else digest

    def _install_gapps(self) -> None:
        if self._initialized():
            raise RuntimeError("Waydroid is already initialized. Remove it before installing a new image.")
        command = ["waydroid", "init", "--system_type", "GAPPS"]
        missing_channels = "You must provide 'System OTA' and 'Vendor OTA' URLs"
        try:
            output = run_init(command, self._set_image_progress)
        except RuntimeError as error:
            if self._initialized() or missing_channels not in str(error):
                raise
            output = str(error)
        # Some distributions ship without default OTA channels.
        if not self._initialized() and missing_channels in output:
            output = run_init([
                *command,
                "--system_channel", "https://ota.waydro.id/system",
                "--vendor_channel", "https://ota.waydro.id/vendor",
            ], self._set_image_progress)
        if not self._initialized():
            raise RuntimeError(output or "Waydroid did not finish initializing its image")

    def _initialize_image(self, locale: str | None) -> dict[str, bool]:
        user, uid, home = self._user()
        data = self._data_home(home, uid) / "waydroid/data"
        initialized = self._initialized()
        new_data = not initialized and not data.exists()
        if not initialized:
            self._install_gapps()
        result = {"languageSet": True, "mediaVolumeSet": True}
        with self._package_session(lambda stage: self._set_image_progress(stage, None)):
            if new_data:
                self._set_image_progress("audio", None)
                try:
                    set_media_volume_max(self._run)
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    decky.logger.warning("Initial Android media volume setup failed: %s", error)
                    result["mediaVolumeSet"] = False
            if new_data and locale:
                self._set_image_progress("language", None)
                try:
                    self._set_initial_locale(locale)
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    decky.logger.warning("Initial Android language setup failed: %s", error)
                    result["languageSet"] = False
            self._set_image_progress("apps", None)
            self._wait_for_app_entries(user, uid, home)
        return result

    def _set_initial_locale(self, locale: str) -> None:
        tags = locale if locale.lower().split("-")[0] == "en" else f"{locale},en-US"
        helper = Path(decky.DECKY_PLUGIN_DIR) / "bin/waydroid-verifier.dex"
        run_dex(self._run, helper, container_identity, container_identity(), "waydroid.manager.SetupLocale", tags)
        for _ in range(10):
            saved = self._run(["waydroid", "shell", "--", "settings", "--user", "0", "get", "system", "system_locales"])
            if saved.casefold() == tags.casefold():
                return
            time.sleep(0.5)
        raise RuntimeError("Android did not save the requested language list")

    def _user_command(self, user: str, uid: int, home: Path) -> list[str]:
        return [
            "runuser", "-u", user, "--", "env",
            f"HOME={home}", f"XDG_RUNTIME_DIR=/run/user/{uid}",
            f"XDG_DATA_HOME={self._data_home(home, uid)}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
        ]

    def _wait_for_app_entries(self, user: str, uid: int, home: Path) -> None:
        command = [*self._user_command(user, uid, home), "waydroid", "app", "list"]
        directory = self._data_home(home, uid) / "applications"
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                expected = launcher_packages(self._run(command, timeout=5))
            except (RuntimeError, subprocess.TimeoutExpired):
                expected = set()
            exported = {entry.stem.removeprefix("waydroid.") for entry in directory.glob("waydroid.*.desktop")}
            if expected and expected <= exported:
                return
            time.sleep(1)
        raise RuntimeError("IMAGE_APP_EXPORT_TIMEOUT")

    async def install_gapps(self, locale: str | None = None) -> dict[str, bool]:
        if locale is not None and (not isinstance(locale, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,4}", locale)):
            locale = "en-US"
        async with self._package_lock:
            self._set_image_progress("preparing", None)
            try:
                return await asyncio.to_thread(self._initialize_image, locale)
            finally:
                self._image_progress = None

    def _set_image_progress(self, stage: str, percent: int | None) -> None:
        self._image_progress = {"stage": stage, "percent": percent}

    async def get_image_progress(self) -> dict[str, str | int | None] | None:
        return self._image_progress

    def _install_file(self, value: str) -> Path:
        _, _, home = self._user()
        try:
            path = Path(value).resolve(strict=True)
            path.relative_to(home)
        except (OSError, ValueError):
            raise RuntimeError("INVALID_PACKAGE_FILE")
        if not path.is_file() or path.suffix.lower() not in {".apk", ".xapk"}:
            raise RuntimeError("INVALID_PACKAGE_FILE")
        return path

    def _require_session(self) -> None:
        # Waydroid status contacts D-Bus and can activate a stopped service.
        if not self._service_running():
            raise RuntimeError("WAYDROID_NOT_RUNNING")
        try:
            status = self._run(["waydroid", "status"])
        except RuntimeError as error:
            raise RuntimeError("WAYDROID_NOT_RUNNING") from error
        if not re.search(r"^Session:\s*RUNNING$", status, re.MULTILINE):
            raise RuntimeError("WAYDROID_NOT_RUNNING")

    @contextmanager
    def _package_session(self, progress: Callable[[str], None] = lambda stage: None):
        if not self._initialized():
            raise RuntimeError("WAYDROID_NOT_INSTALLED")
        try:
            self._require_session()
        except RuntimeError:
            pass
        else:
            self._wait_for_android(progress)
            yield
            return

        if self._control and self._control.launch:
            raise RuntimeError("WAYDROID_LAUNCH_STARTING")

        user, uid, home = self._user()
        wayland = steam_wayland_socket(uid)
        if not wayland:
            raise RuntimeError("WAYDROID_START_FAILED")
        user_command = self._user_command(user, uid, home)
        unit = f"waydroid-manager-package-{uuid.uuid4().hex}"
        unit_status = [*user_command, "systemctl", "--user", "show", unit, "--property=ActiveState", "--value"]
        service_was_active = self._service_running()
        completed = False
        try:
            progress("starting")
            self._run(["systemctl", "start", SERVICE])
            # Session start keeps Android hidden until an app or the full UI is requested.
            self._run([
                *user_command, "systemd-run", "--user", "--collect", "--quiet",
                f"--unit={unit}", "--property=KillMode=control-group", "--property=TimeoutStopSec=45s",
                "env", f"WAYLAND_DISPLAY={wayland}", "waydroid", "session", "start",
            ])
            self._wait_for_android(progress, unit_status)
            with keep_package_guest_running(self._run):
                yield
            completed = True
        finally:
            progress("cleaning")
            try:
                self._cleanup_package_session(user_command, unit, unit_status, service_was_active)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                decky.logger.warning("Could not close the temporary Android session: %s", error)
                if completed:
                    raise RuntimeError("WAYDROID_CLEANUP_FAILED") from error

    def _cleanup_package_session(self, user_command: list[str], unit: str,
                                 unit_status: list[str], service_was_active: bool) -> None:
        try:
            try:
                state = self._run(unit_status, timeout=5)
            except subprocess.TimeoutExpired:
                state = None
            if state is None or state in {"active", "activating", "deactivating", "reloading"}:
                self._run([*user_command, "systemctl", "--user", "stop", unit], timeout=60)
        finally:
            if not service_was_active and self._service_running():
                try:
                    self._require_session()
                except RuntimeError:
                    self._run(["systemctl", "stop", SERVICE])

    def _wait_for_android(self, progress: Callable[[str], None], unit_status: list[str] | None = None) -> None:
        progress("booting")
        try:
            self._wait_for_boot(unit_status)
        finally:
            if warning := vendor_overlay_warning(WAYDROID_DIR):
                decky.logger.warning("%s", warning)

    def _wait_for_boot(self, unit_status: list[str] | None) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                if self._run(["waydroid", "shell", "--", "getprop", "sys.boot_completed"], timeout=10) == "1":
                    return
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            if unit_status:
                try:
                    state = self._run(unit_status, timeout=5)
                except subprocess.TimeoutExpired:
                    state = None
                if state is not None and state not in {"active", "activating"}:
                    raise RuntimeError("WAYDROID_START_FAILED")
            else:
                self._require_session()
            time.sleep(1)
        raise RuntimeError("WAYDROID_START_FAILED")

    def _check_package_result(self, output: str) -> None:
        check_result(output)

    def _install_package(self, value: str) -> bool:
        self._set_package_progress("install", value, "preparing")
        try:
            self._install_archive(value)
            self._set_package_progress("install", value, "complete")
            return True
        except InstallCancelled:
            self._set_package_progress("install", value, "cancelled")
            return False
        except Exception:
            self._set_package_progress("install", value, "failed")
            raise

    def _install_archive(self, value: str) -> None:
        if not self._initialized():
            raise RuntimeError("WAYDROID_NOT_INSTALLED")
        path = self._install_file(value)
        _, _, home = self._user()
        report = lambda stage: self._set_package_progress("install", value, stage)
        try:
            with open_as_user(self._user_files_helper(), home, path) as source, zipfile.ZipFile(source) as archive:
                members = apk_members(archive, path.suffix.lower())
                with self._package_session(report), stage_apks(archive, members) as parts:
                    report("installing")
                    install_apks(self._run, parts, commit=lambda session: self._commit_package_install(session, value))
                    self._removable_packages()
        except zipfile.BadZipFile as error:
            raise RuntimeError("INVALID_PACKAGE_ARCHIVE") from error

    async def install_package(self, value: str) -> bool:
        async with self._package_lock:
            return await asyncio.to_thread(self._install_package, value)

    def _commit_package_install(self, session: str, target: str) -> str:
        helper = Path(decky.DECKY_PLUGIN_DIR) / "bin/waydroid-verifier.dex"
        return commit_install(
            ["waydroid", "shell", "--", "pm", "install-commit", session],
            InstallVerification(self._run, session, helper),
            lambda active: self._confirm_package_install(target, active),
        )

    def _confirm_package_install(self, target: str, active: Callable[[], bool]) -> bool | None:
        token, event, decision = uuid.uuid4().hex, threading.Event(), []
        self._install_confirmation = (target, token, event, decision)
        self._set_package_progress("install", target, "confirmation")
        deadline = time.monotonic() + 180
        try:
            while active():
                if event.wait(0.5):
                    return decision[0]
                if time.monotonic() >= deadline:
                    raise RuntimeError("PACKAGE_INSTALL_TIMEOUT")
            return None
        finally:
            self._install_confirmation = None
            self._set_package_progress("install", target, "installing")

    async def confirm_package_install(self, target: str, token: str, approved: bool) -> None:
        pending = self._install_confirmation
        if not pending or pending[:2] != (target, token) or type(approved) is not bool or pending[2].is_set():
            raise RuntimeError("ANDROID_VERIFICATION_UNAVAILABLE")
        pending[3].append(approved)
        pending[2].set()

    async def _change_service(self, action: str) -> None:
        async with self._package_lock:
            await asyncio.to_thread(self._run, ["systemctl", action, SERVICE])

    async def start_service(self) -> None:
        await self._change_service("start")

    async def stop_service(self) -> None:
        await self._change_service("stop")

    async def restart_service(self) -> None:
        await self._change_service("restart")

    async def _ensure_service(self) -> None:
        if not self._initialized():
            raise RuntimeError("WAYDROID_NOT_INSTALLED")
        await self.start_service()

    def _uninstall_package(self, package: str, account_id: int | None = None) -> int | None:
        if not PACKAGE_RE.fullmatch(package):
            raise RuntimeError("Invalid Android package name")
        self._set_package_progress("uninstall", package, "preparing")
        try:
            with self._package_session(lambda stage: self._set_package_progress("uninstall", package, stage)):
                shortcut_id = self._remove_installed_package(package, account_id)
            self._set_package_progress("uninstall", package, "library")
            return shortcut_id
        except Exception:
            self._set_package_progress("uninstall", package, "failed")
            raise

    def _set_package_progress(self, operation: str, target: str, stage: str) -> None:
        self._package_progress = {"operation": operation, "target": target, "stage": stage}

    async def get_package_progress(self, operation: str, target: str) -> dict[str, str]:
        progress = self._package_progress
        if (progress.get("operation"), progress.get("target")) == (operation, target):
            result = {"stage": progress["stage"]}
            pending = self._install_confirmation
            if operation == "install" and pending and pending[0] == target:
                result["confirmation"] = pending[1]
            return result
        return {"stage": "preparing"}

    def _queue_shortcut_removals(self, home: Path, state: dict, active_account: int | None,
                                 package: str | None = None) -> list[int]:
        accounts = {int(key) for key in state["accounts"]}
        if active_account is not None:
            accounts.add(active_account)
        try:
            accounts.update(known_accounts(home))
        except (OSError, RuntimeError, ValueError):
            pass
        active_ids = []
        for account_id in sorted(accounts):
            history = self._account_state(home, state, account_id)
            owners = {app_id: key for key, app_id in history["shortcuts"].items() if key not in history["removedShortcuts"]}
            try:
                path = self._shortcuts_path(home, account_id)
                owners.update(shortcut_owners(path, self._launcher()))
            except (OSError, RuntimeError, ValueError):
                pass
            queued = {str(app_id): key for app_id, key in owners.items() if key is not None
                      and (package is None or key == package)}
            history["pendingRemovals"].update(queued)
            if account_id == active_account:
                active_ids = sorted(map(int, history["pendingRemovals"] if package is None else queued))
            if package is None:
                state["accounts"][str(account_id)] = {**StateStore.shortcut_defaults(),
                                                       "pendingRemovals": history["pendingRemovals"]}
            else:
                self._forget_app_history(history, package)
        if "legacy" in state:
            if package is None:
                state.pop("legacy")
            else:
                self._forget_app_history(state["legacy"], package)
        return active_ids

    @staticmethod
    def _forget_app_history(history: dict, package: str) -> None:
        history["shortcuts"].pop(package, None)
        for key in ("observedApps", "pendingApps", "removedShortcuts"):
            history[key] = [item for item in history[key] if item != package]

    def _remove_installed_package(self, package: str, account_id: int | None = None) -> int | None:
        self._set_package_progress("uninstall", package, "checking")
        if package not in self._removable_packages(allow_cached=False):
            raise RuntimeError("APP_NOT_REMOVABLE")
        _, uid, home = self._user()
        self._set_package_progress("uninstall", package, "removing")
        output = self._run(["waydroid", "shell", "--", "pm", "uninstall", package], timeout=60)
        self._check_package_result(output)
        with self._state_lock:
            try:
                path = self._data_home(home, uid) / "applications" / f"waydroid.{package}.desktop"
                self._user_files(home, "unlink", str(path))
            finally:
                with self._edit_state(home) as state:
                    state["removableApps"] = [item for item in state["removableApps"] if item != package]
                    queued = self._queue_shortcut_removals(home, state, account_id, package)
        return next(iter(queued), None)

    async def uninstall_app(self, package: str, account_id: int | None = None) -> int | None:
        async with self._package_lock:
            return await asyncio.to_thread(self._uninstall_package, package, account_id)

    def _remove_image(self, account_id: int | None) -> list[int]:
        user, uid, home = self._user()
        data_home = self._data_home(home, uid)
        user_data = data_home / "waydroid"
        applications = data_home / "applications"
        data_paths = (WAYDROID_DIR, user_data)
        for path in (*data_paths, applications):
            require_unredirected(path)
        with owned_directory(data_home, home.stat().st_uid) as pinned_data:
            self._run(["systemctl", "stop", SERVICE])
            require_unmounted(data_paths)
            self._set_image_progress("deleting", None)
            if WAYDROID_DIR.exists():
                shutil.rmtree(WAYDROID_DIR)
            if pinned_data and (guest_data := pinned_data / "waydroid").exists():
                shutil.rmtree(guest_data)
        with self._edit_state(home) as state:
            state["removableApps"] = []
            shortcuts = self._queue_shortcut_removals(home, state, account_id)
        require_unredirected(applications)
        for entry in applications.glob("waydroid.*.desktop"):
            self._user_files(home, "unlink", str(entry))
        decky.logger.info("Removed Waydroid data for %s", user)
        return shortcuts

    async def remove_waydroid(self, account_id: int | None = None) -> list[int]:
        async with self._package_lock:
            if self._control and self._control.launch:
                raise RuntimeError("WAYDROID_LAUNCH_ACTIVE")
            self._set_image_progress("stopping", None)
            try:
                return await asyncio.to_thread(self._remove_image, account_id)
            finally:
                self._image_progress = None

    async def _main(self):
        self._frame_limiter = FrameLimiter(self._run)
        self._policy = LaunchPolicy(self._run, container_identity)
        self._gpu_metrics = GpuMetrics()
        self._metrics_error = None
        self._runtime_lock = asyncio.Lock()
        self._package_lock = asyncio.Lock()
        _, uid, _ = self._user()
        relay = Path(decky.DECKY_PLUGIN_DIR).resolve() / "bin/waydroid-wayland-relay"
        self._control = ServiceControl(control_path(uid), uid, self._ensure_service, relay, self._prepare_launch,
                                       self._launch_policy, self._release_launch)
        await self._control.open()
        decky.logger.info("Waydroid Manager loaded")

    async def _unload(self):
        await self._control.close()
        try:
            async with self._runtime_lock:
                _, uid, _ = self._user()
                await asyncio.to_thread(self._gpu_metrics.close, uid)
                await asyncio.to_thread(self._frame_limiter.restore)
        finally:
            await asyncio.to_thread(self._stop_input_sync)

    async def sync_runtime(self, fps: int | None) -> None:
        if fps is not None and (type(fps) is not int or not 0 <= fps <= 1000):
            raise RuntimeError("Invalid frame limit")
        async with self._runtime_lock:
            _, uid, _ = self._user()
            registration = self._control.launch
            guest = None
            if registration and self._control.release_task is None and process_identity(registration.process[0]) == registration.process:
                guest = await asyncio.to_thread(registered_guest, registration.display)
            launch = registration.process if guest and registration else None
            metrics = registration.display.with_name("metrics") if launch and registration else None
            try:
                await asyncio.to_thread(self._gpu_metrics.sync, launch, uid, metrics, guest)
                self._metrics_error = None
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                if str(error) != self._metrics_error:
                    decky.logger.warning("GPU metrics unavailable: %s", error)
                self._metrics_error = str(error)
            await asyncio.to_thread(self._frame_limiter.sync, fps, launch, guest)
