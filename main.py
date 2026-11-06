import base64
import asyncio
import configparser
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
from waydroid_manager.frame_limit import FrameLimiter
from waydroid_manager.proc import active_launch, clean_env
from waydroid_manager.artwork import apk_images, missing_artwork, package_apks, persistent_apks
from waydroid_manager.metrics import GpuMetrics
from waydroid_manager.packages import apk_members, stage_apks
from waydroid_manager.steam import read_shortcuts, shortcuts_path, shortcut_key, migrated_launch_options
from waydroid_manager.container import CONFIG_DIR, SERVICE, container_pid
from waydroid_manager.control import ServiceControl, control_path
from waydroid_manager.state import StateStore


PACKAGE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
WAYDROID_DIR = CONFIG_DIR
MAX_ICON_BYTES = 2 * 1024 * 1024
WAYDROID_SHORTCUT_KEY = "waydroid"


class Plugin:
    INPUT_SYNC_UNIT = "waydroid-manager-input-sync.service"

    def __init__(self):
        self._state_lock = threading.RLock()
        self._package_progress: dict[str, str] = {}

    @contextmanager
    def _edit_state(self, home: Path):
        with self._state_lock:
            state = self._load_state(home)
            yield state
            self._save_state(home, state)

    def _run(self, command: list[str], timeout: int = 30) -> str:
        result = subprocess.run(
            command,
            env=clean_env(),
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
        return (WAYDROID_DIR / "waydroid.cfg").is_file()

    def _service_state(self, action: str) -> bool:
        return subprocess.run(
            ["systemctl", "is-" + action, SERVICE],
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

    def _start_input_sync(self) -> None:
        subprocess.run(
            ["systemctl", "stop", self.INPUT_SYNC_UNIT],
            env=clean_env(), timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        _, uid, _ = self._user()
        self._run([
            "systemd-run", "--quiet", "--no-block", "--collect",
            "--unit=waydroid-manager-input-sync",
            str(self._input_sync()), str(uid),
        ])

    def _stop_input_sync(self) -> None:
        subprocess.run(
            ["systemctl", "stop", self.INPUT_SYNC_UNIT],
            env=clean_env(), timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def _steam_graphics_environment(self, uid: int) -> dict[str, str]:
        candidates: list[tuple[bool, dict[str, str]]] = []
        for process in Path("/proc").glob("[0-9]*"):
            try:
                if process.stat().st_uid != uid:
                    continue
                arguments = (process / "cmdline").read_bytes().split(b"\0")
                names = {argument.rsplit(b"/", 1)[-1] for argument in arguments}
                if not names.intersection({b"steam", b"steamwebhelper"}):
                    continue

                environment = {}
                for value in (process / "environ").read_bytes().split(b"\0"):
                    key, separator, content = value.partition(b"=")
                    if separator and key in {b"DISPLAY", b"XAUTHORITY", b"WAYLAND_DISPLAY", b"GAMESCOPE_WAYLAND_DISPLAY"}:
                        environment[key.decode()] = content.decode(errors="ignore")
                if "DISPLAY" in environment:
                    candidates.append((b"steam" in names, environment))
            except OSError:
                continue

        if candidates:
            candidates.sort(key=lambda candidate: not candidate[0])
            return candidates[0][1]
        raise RuntimeError("Could not identify Steam's active Game Mode display")

    def _icon_data_uri(self, value: str, home: Path) -> str:
        try:
            icon = Path(value).resolve(strict=True)
            icon.relative_to(home / ".local/share/waydroid/data/icons")
        except (OSError, ValueError):
            return ""

        if icon.suffix.lower() != ".png" or icon.stat().st_size > MAX_ICON_BYTES:
            return ""
        return "data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode("ascii")

    def _state_path(self, home: Path) -> Path:
        return StateStore(home).path

    def _load_state(self, home: Path) -> dict[str, Any]:
        return StateStore(home).load()

    def _save_state(self, home: Path, state: dict[str, Any]) -> None:
        StateStore(home).save(state)

    def _shortcut_ids(self, home: Path) -> dict[str, int]:
        state = self._load_state(home)
        shortcuts = state["shortcuts"]
        if not isinstance(shortcuts, dict):
            return {}
        recorded = {key: value for key, value in shortcuts.items() if isinstance(key, str) and isinstance(value, int)}
        removed = set(state["removedShortcuts"])
        try:
            saved_shortcuts = read_shortcuts(self._shortcuts_path(home))
        except (OSError, RuntimeError, ValueError):
            return recorded

        launcher = str(self._launcher())
        ids: dict[str, int] = {}
        for _, (_, shortcut) in saved_shortcuts.items():
            shortcut = {key.casefold(): value for key, value in shortcut.items()}
            exe = str(shortcut.get("exe", (1, ""))[1]).strip('"')
            options = str(shortcut.get("launchoptions", (1, ""))[1])
            app_id = shortcut.get("appid", (2, 0))[1]
            if not isinstance(app_id, int):
                continue
            normalized_id = app_id & 0xFFFFFFFF
            key = shortcut_key(options) if Path(exe).resolve() == Path(launcher).resolve() else None
            if key is None:
                continue
            if key not in removed:
                ids[key] = normalized_id
        return ids

    def _removable_packages(self, allow_cached: bool = True) -> set[str]:
        _, _, home = self._user()
        if not self._service_state("active"):
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

    def _desktop_entries(self, removable_packages: set[str] | None = None) -> list[dict[str, Any]]:
        _, _, home = self._user()
        directory = home / ".local/share/applications"
        shortcut_ids = self._shortcut_ids(home)
        apps: list[dict[str, Any]] = []
        for entry in sorted(directory.glob("waydroid.*.desktop")):
            package = entry.stem.removeprefix("waydroid.")
            if not PACKAGE_RE.fullmatch(package):
                continue
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(entry, encoding="utf-8")
                data = parser["Desktop Entry"]
                if data.get("Exec") != f"waydroid app launch {package}":
                    continue
                icon_path = data.get("Icon", "")
                apps.append({
                    "name": data.get("Name", package),
                    "package": package,
                    "icon": self._icon_data_uri(icon_path, home),
                    "iconPath": icon_path,
                    "shortcutId": shortcut_ids.get(package),
                    "removable": package in removable_packages if removable_packages is not None else False,
                })
            except (OSError, KeyError, configparser.Error):
                continue
        return sorted(apps, key=lambda app: app["name"].casefold())

    def _shortcuts_path(self, home: Path) -> Path:
        return shortcuts_path(home)

    def _status(self) -> dict[str, Any]:
        _, uid, home = self._user()
        state = self._load_state(home)
        shortcut_ids = self._shortcut_ids(home)
        try:
            graphics = self._steam_graphics_environment(uid)
            display = graphics.get("GAMESCOPE_WAYLAND_DISPLAY", "")
            session_available = bool(display and (Path(f"/run/user/{uid}") / display).is_socket())
        except RuntimeError:
            session_available = False
        return {
            "initialized": self._initialized(),
            "serviceRunning": self._service_state("active"),
            "sessionAvailable": session_available,
            "autoAddApps": state["autoAddApps"],
            "userHome": str(home),
            "waydroidShortcutId": shortcut_ids.get(WAYDROID_SHORTCUT_KEY),
        }

    async def get_status(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._status)

    def _list_apps(self) -> list[dict[str, Any]]:
        return self._desktop_entries(self._removable_packages()) if self._initialized() else []

    async def list_apps(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_apps)

    def _shortcut_details(self, name: str, package: str | None = None, icon: str = "") -> dict[str, str]:
        _, _, home = self._user()
        return {
            "name": name,
            "exe": str(self._launcher()),
            "startDir": str(home),
            "launchOptions": "full" if package is None else f"app {package}",
            "icon": icon,
            "key": WAYDROID_SHORTCUT_KEY if package is None else package,
        }

    def _validate_shortcut_key(self, key: str) -> None:
        if key == WAYDROID_SHORTCUT_KEY:
            return
        if not PACKAGE_RE.fullmatch(key):
            raise RuntimeError("Invalid Android package name")

    async def record_shortcut(self, key: str, app_id: int) -> None:
        self._validate_shortcut_key(key)
        if not isinstance(app_id, int) or app_id == 0:
            raise RuntimeError("Steam did not return a valid shortcut ID")
        _, _, home = self._user()
        with self._edit_state(home) as state:
            state["shortcuts"][key] = app_id
            state["removedShortcuts"] = [item for item in state["removedShortcuts"] if item != key]
            state["pendingApps"] = [item for item in state["pendingApps"] if item != key]

    async def remove_shortcut_record(self, key: str) -> None:
        self._validate_shortcut_key(key)
        _, _, home = self._user()
        with self._edit_state(home) as state:
            state["shortcuts"].pop(key, None)
            state["pendingApps"] = [item for item in state["pendingApps"] if item != key]
            if key not in state["removedShortcuts"]:
                state["removedShortcuts"].append(key)

    async def set_auto_add_apps(self, enabled: bool) -> None:
        _, _, home = self._user()
        with self._edit_state(home) as state:
            state["autoAddApps"] = enabled
            if enabled:
                state["observedApps"] = sorted({*state["observedApps"], *(app["package"] for app in self._desktop_entries())})

    def _pending_auto_shortcuts(self, live_ids: list[int] | None = None) -> list[dict[str, str]]:
        if self._initialized():
            self._removable_packages()
        _, _, home = self._user()
        with self._state_lock:
            return self._update_auto_shortcuts(home, live_ids)

    def _update_auto_shortcuts(self, home: Path, live_ids: list[int] | None) -> list[dict[str, str]]:
        state = self._load_state(home)
        if live_ids is not None:
            ids = set(live_ids)
            discovered = self._shortcut_ids(home)
            for key, app_id in list(state["shortcuts"].items()):
                if app_id in ids:
                    continue
                replacement = discovered.get(key)
                if replacement in ids:
                    state["shortcuts"][key] = replacement
                else:
                    state["shortcuts"].pop(key)
                    if key not in state["removedShortcuts"]:
                        state["removedShortcuts"].append(key)
                    state["pendingApps"] = [item for item in state["pendingApps"] if item != key]
            self._save_state(home, state)
        if not state["autoAddApps"]:
            return []

        apps = self._desktop_entries()
        installed = {app["package"]: app for app in apps}
        observed = set(state["observedApps"])
        removed = set(state["removedShortcuts"])
        recorded = set(state["shortcuts"])
        pending = set(state["pendingApps"])
        pending.update(package for package, app in installed.items() if package not in observed and package not in removed and package not in recorded and not app["shortcutId"])
        pending = {package for package in pending if package in installed and not installed[package]["shortcutId"]}
        state["observedApps"] = sorted(observed | set(installed))
        state["pendingApps"] = sorted(pending & set(installed))
        self._save_state(home, state)
        return [
            self._shortcut_details(app["name"], package, app["iconPath"])
            for package, app in installed.items()
            if package in state["pendingApps"]
        ]

    async def pending_auto_shortcuts(self, live_ids: list[int] | None = None) -> list[dict[str, str]]:
        return await asyncio.to_thread(self._pending_auto_shortcuts, live_ids)

    def _legacy_shortcuts(self) -> list[dict[str, Any]]:
        _, _, home = self._user()
        result = []
        for _, (_, entry) in read_shortcuts(self._shortcuts_path(home)).items():
            entry = {key.casefold(): value for key, value in entry.items()}
            exe = str(entry.get("exe", (1, ""))[1]).strip('"')
            options = migrated_launch_options(str(entry.get("launchoptions", (1, ""))[1]))
            app_id = entry.get("appid", (2, 0))[1]
            if Path(exe).resolve() == self._launcher().resolve() and options and isinstance(app_id, int) and app_id:
                result.append({"appId": app_id & 0xFFFFFFFF, "launchOptions": options})
        return result

    async def legacy_shortcuts(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._legacy_shortcuts)

    async def get_waydroid_shortcut(self) -> dict[str, str]:
        return self._shortcut_details("Waydroid")

    async def get_app_shortcut(self, package: str) -> dict[str, str]:
        if not PACKAGE_RE.fullmatch(package):
            raise RuntimeError("Invalid Android package name")
        app = next((item for item in self._desktop_entries() if item["package"] == package), None)
        if not app:
            raise RuntimeError("Android app is no longer installed")
        return self._shortcut_details(app["name"], package, app["iconPath"])

    async def pending_shortcut_artwork(self) -> list[dict[str, Any]]:
        _, _, home = self._user()
        try:
            grid = self._shortcuts_path(home).parent / "grid"
        except RuntimeError:
            return []
        return [{"key": key, "appId": app_id} for key, app_id in self._shortcut_ids(home).items()
                if missing_artwork(grid, app_id)]

    def _shortcut_artwork(self, key: str, app_id: int) -> dict[str, Any]:
        self._validate_shortcut_key(key)
        _, _, home = self._user()
        if self._shortcut_ids(home).get(key) != app_id:
            raise RuntimeError("The Steam shortcut no longer exists")
        roles = missing_artwork(self._shortcuts_path(home).parent / "grid", app_id)
        app = next((item for item in self._desktop_entries() if item["package"] == key), None)
        result = {"roles": roles, "ready": True, "name": app["name"] if app else "Waydroid", "icon": app["icon"] if app else "", "images": []}
        if not roles or not app:
            return result
        try:
            apks = persistent_apks(home / ".local/share/waydroid/data", key)
            if not apks and self._service_state("active"):
                pid = container_pid()
                if pid:
                    # Keep proc's root link intact for the container mount tree.
                    root = Path("/proc") / str(pid) / "root"
                    apks = package_apks(root, self._run(["waydroid", "shell", "--", "pm", "path", key]))
            result["images"] = apk_images(apks)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, subprocess.SubprocessError):
            pass
        return result

    async def get_shortcut_artwork(self, key: str, app_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._shortcut_artwork, key, app_id)

    def _install_gapps(self) -> None:
        if self._initialized():
            raise RuntimeError("Waydroid is already initialized. Remove it before installing a new image.")
        self._run(["waydroid", "init", "--system_type", "GAPPS"], timeout=1800)
        if not self._initialized():
            raise RuntimeError("Waydroid did not finish initializing its image")

    async def install_gapps(self) -> None:
        async with self._package_lock:
            await asyncio.to_thread(self._install_gapps)

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
        if not self._service_state("active"):
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
            yield
            return

        user, uid, home = self._user()
        graphics = self._steam_graphics_environment(uid)
        wayland = graphics.get("GAMESCOPE_WAYLAND_DISPLAY") or graphics.get("WAYLAND_DISPLAY")
        if not wayland:
            raise RuntimeError("WAYDROID_START_FAILED")
        user_command = [
            "runuser", "-u", user, "--", "env",
            f"HOME={home}", f"XDG_RUNTIME_DIR=/run/user/{uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
        ]
        unit = f"waydroid-manager-package-{uuid.uuid4().hex}"
        service_was_active = self._service_state("active")
        try:
            progress("starting")
            self._run(["systemctl", "start", SERVICE])
            # Session start keeps Android hidden until an app or the full UI is requested.
            self._run([
                *user_command, "systemd-run", "--user", "--collect", "--quiet",
                f"--unit={unit}", "--property=KillMode=control-group",
                "env", f"WAYLAND_DISPLAY={wayland}", "waydroid", "session", "start",
            ])
            progress("booting")
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                try:
                    ready = self._run(["waydroid", "shell", "--", "getprop", "sys.boot_completed"], timeout=10)
                    if ready == "1":
                        break
                except (RuntimeError, subprocess.TimeoutExpired):
                    pass
                if self._run([*user_command, "systemctl", "--user", "show", unit, "--property=ActiveState", "--value"]) not in {"active", "activating"}:
                    raise RuntimeError("WAYDROID_START_FAILED")
                time.sleep(1)
            else:
                raise RuntimeError("WAYDROID_START_FAILED")
            yield
        finally:
            progress("cleaning")
            # Stop only our temporary unit, never a replacement session started by Steam.
            state = self._run([*user_command, "systemctl", "--user", "show", unit, "--property=ActiveState", "--value"])
            if state in {"active", "activating"}:
                self._run([*user_command, "systemctl", "--user", "stop", unit])
            if not service_was_active:
                try:
                    self._require_session()
                except RuntimeError:
                    self._run(["systemctl", "stop", SERVICE])

    def _check_package_result(self, output: str) -> None:
        if "Success" not in output.splitlines():
            raise RuntimeError(output or "PACKAGE_OPERATION_FAILED")

    def _install_package(self, value: str) -> None:
        self._set_package_progress("install", value, "preparing")
        try:
            self._install_archive(value)
            self._set_package_progress("install", value, "complete")
        except Exception:
            self._set_package_progress("install", value, "failed")
            raise

    def _install_archive(self, value: str) -> None:
        if not self._initialized():
            raise RuntimeError("WAYDROID_NOT_INSTALLED")
        path = self._install_file(value)
        _, _, home = self._user()
        host_dir = home / ".local/share/waydroid/data/local/tmp" / f"waydroid-manager-{uuid.uuid4().hex}"
        report = lambda stage: self._set_package_progress("install", value, stage)
        try:
            with zipfile.ZipFile(path) as archive:
                members = apk_members(archive, path.suffix.lower())
                with self._package_session(report):
                    report("checking")
                    if not host_dir.parent.resolve().is_relative_to(home.resolve()):
                        raise RuntimeError("INVALID_PACKAGE_FILE")
                    installed = stage_apks(archive, members, host_dir)
                    guest_dir = f"/data/local/tmp/{host_dir.name}"
                    action = "install" if path.suffix.lower() == ".apk" else "install-multiple"
                    report("installing")
                    output = self._run(["waydroid", "shell", "--", "pm", action, "-r", *[f"{guest_dir}/{name}" for name in installed]], timeout=300)
                    self._check_package_result(output)
        except zipfile.BadZipFile as error:
            raise RuntimeError("INVALID_PACKAGE_ARCHIVE") from error
        finally:
            shutil.rmtree(host_dir, ignore_errors=True)

    async def install_package(self, value: str) -> None:
        async with self._package_lock:
            await asyncio.to_thread(self._install_package, value)

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

    def _uninstall_package(self, package: str) -> int | None:
        if not PACKAGE_RE.fullmatch(package):
            raise RuntimeError("Invalid Android package name")
        self._set_package_progress("uninstall", package, "preparing")
        try:
            with self._package_session(lambda stage: self._set_package_progress("uninstall", package, stage)):
                shortcut_id = self._remove_installed_package(package)
            self._set_package_progress("uninstall", package, "library")
            return shortcut_id
        except Exception:
            self._set_package_progress("uninstall", package, "failed")
            raise

    def _set_package_progress(self, operation: str, target: str, stage: str) -> None:
        self._package_progress = {"operation": operation, "target": target, "stage": stage}

    async def get_package_progress(self, operation: str, target: str) -> str:
        progress = self._package_progress
        return progress.get("stage", "preparing") if (progress.get("operation"), progress.get("target")) == (operation, target) else "preparing"

    def _remove_installed_package(self, package: str) -> int | None:
        self._set_package_progress("uninstall", package, "checking")
        if package not in self._removable_packages(allow_cached=False):
            raise RuntimeError("APP_NOT_REMOVABLE")
        _, _, home = self._user()
        shortcut_id = self._shortcut_ids(home).get(package)
        self._set_package_progress("uninstall", package, "removing")
        output = self._run(["waydroid", "shell", "--", "pm", "uninstall", package], timeout=60)
        self._check_package_result(output)
        (home / ".local/share/applications" / f"waydroid.{package}.desktop").unlink(missing_ok=True)
        with self._edit_state(home) as state:
            state["shortcuts"].pop(package, None)
            for key in ("observedApps", "pendingApps", "removedShortcuts", "removableApps"):
                state[key] = [item for item in state.get(key, []) if item != package]
        return shortcut_id

    async def uninstall_app(self, package: str) -> int | None:
        async with self._package_lock:
            return await asyncio.to_thread(self._uninstall_package, package)

    def _remove_image(self) -> list[int]:
        user, _, home = self._user()
        shortcuts = sorted(set(self._shortcut_ids(home).values()))
        self._run(["systemctl", "stop", SERVICE])
        if WAYDROID_DIR.exists():
            shutil.rmtree(WAYDROID_DIR)
        user_data = home / ".local/share/waydroid"
        if user_data.exists():
            shutil.rmtree(user_data)
        for entry in (home / ".local/share/applications").glob("waydroid.*.desktop"):
            entry.unlink(missing_ok=True)
        self._state_path(home).unlink(missing_ok=True)
        decky.logger.info("Removed Waydroid data for %s", user)
        return shortcuts

    async def remove_waydroid(self) -> list[int]:
        async with self._package_lock:
            return await asyncio.to_thread(self._remove_image)

    async def _main(self):
        self._frame_limiter = FrameLimiter(self._run)
        self._gpu_metrics = GpuMetrics()
        self._metrics_error = None
        self._runtime_lock = asyncio.Lock()
        self._package_lock = asyncio.Lock()
        _, uid, _ = self._user()
        self._control = ServiceControl(control_path(uid), uid, self._ensure_service)
        await self._control.open()
        try:
            await asyncio.to_thread(self._start_input_sync)
        except Exception:
            await self._control.close()
            raise
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
            relay = Path(decky.DECKY_PLUGIN_DIR).resolve() / "bin/waydroid-wayland-relay"
            launch = await asyncio.to_thread(active_launch, uid, relay)
            try:
                await asyncio.to_thread(self._gpu_metrics.sync, launch, uid)
                self._metrics_error = None
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                if str(error) != self._metrics_error:
                    decky.logger.warning("GPU metrics unavailable: %s", error)
                self._metrics_error = str(error)
            await asyncio.to_thread(self._frame_limiter.sync, fps or 0, launch)
