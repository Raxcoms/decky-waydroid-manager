import base64
import asyncio
import configparser
import json
import os
import pwd
import re
import shutil
import struct
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import decky
from waydroid_manager.frame_limit import FrameLimiter, active_launch
from waydroid_manager.proc import clean_env
from waydroid_manager.artwork import apk_images, missing_artwork


PACKAGE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
WAYDROID_DIR = Path("/var/lib/waydroid")
SERVICE = "waydroid-container.service"
MAX_ICON_BYTES = 2 * 1024 * 1024
WAYDROID_SHORTCUT_KEY = "waydroid"
LAUNCH_WRAPPER = "/usr/libexec/armada/armada-game-launch"


class Plugin:
    INPUT_SYNC_UNIT = "waydroid-manager-input-sync.service"

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
            home = Path(user_home)
            if home.is_dir():
                account = pwd.getpwuid(home.stat().st_uid)
                return account.pw_name, account.pw_uid, home

        for account in pwd.getpwall():
            if account.pw_uid >= 1000 and Path(account.pw_dir).is_dir():
                return account.pw_name, account.pw_uid, Path(account.pw_dir)
        raise RuntimeError("Could not find the ArmadaOS user")

    def _initialized(self) -> bool:
        return (WAYDROID_DIR / "waydroid.cfg").is_file()

    def _service_state(self, action: str) -> bool:
        return subprocess.run(
            ["systemctl", "is-" + action, SERVICE],
            env=clean_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0

    def _panel_resolution(self) -> dict[str, int] | None:
        resolutions: set[tuple[int, int]] = set()
        for modes in Path("/sys/class/drm").glob("*/modes"):
            try:
                for mode in modes.read_text().splitlines():
                    match = re.fullmatch(r"(\d+)x(\d+)", mode.strip())
                    if match:
                        resolutions.add((int(match.group(1)), int(match.group(2))))
            except OSError:
                continue
        if not resolutions:
            return None
        width, height = max(resolutions, key=lambda mode: mode[0] * mode[1])
        if self._gamescope_orientation() in {"left", "right"}:
            width, height = height, width
        return {"width": width, "height": height}

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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self._run([
            "systemd-run", "--quiet", "--no-block", "--collect",
            "--unit=waydroid-manager-input-sync",
            str(self._input_sync()),
        ])

    def _stop_input_sync(self) -> None:
        subprocess.run(
            ["systemctl", "stop", self.INPUT_SYNC_UNIT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def _steam_gamescope_processes(self) -> dict[str, list[bytes]]:
        processes: dict[str, list[bytes]] = {}
        for process in Path("/proc").glob("[0-9]*"):
            try:
                arguments = (process / "cmdline").read_bytes().split(b"\0")
                if b"--steam" in arguments and any(b"gamescope" in argument for argument in arguments):
                    processes[process.name] = arguments
            except OSError:
                continue
        return processes

    def _gamescope_orientation(self) -> str:
        for arguments in self._steam_gamescope_processes().values():
            for index, argument in enumerate(arguments):
                if argument == b"--force-orientation" and index + 1 < len(arguments):
                    return arguments[index + 1].decode("ascii", errors="ignore")
                if argument.startswith(b"--force-orientation="):
                    return argument.partition(b"=")[2].decode("ascii", errors="ignore")
        return ""

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

    def _start_launcher(self, mode: str, package: str | None = None) -> None:
        if not self._initialized():
            raise RuntimeError("Install the GAPPS image before starting Waydroid")
        if not shutil.which("gamescope"):
            raise RuntimeError("Gamescope is unavailable in this ArmadaOS deployment. Update or repair the deployment before launching Waydroid.")
        self._run(["systemctl", "start", SERVICE])
        user, uid, home = self._user()
        graphics_environment = self._steam_graphics_environment(uid)
        log_path = home / ".local/state/waydroid-manager/launcher.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        os.chown(log_path.parent, uid, pwd.getpwnam(user).pw_gid)
        log_path.touch(exist_ok=True)
        os.chown(log_path, uid, pwd.getpwnam(user).pw_gid)
        environment = [
            f"HOME={home}",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
            f"DISPLAY={graphics_environment['DISPLAY']}",
        ]
        if graphics_environment.get("XAUTHORITY"):
            environment.append(f"XAUTHORITY={graphics_environment['XAUTHORITY']}")
        resolution = self._panel_resolution()
        if resolution:
            environment.extend((
                f"WAYDROID_MANAGER_WIDTH={resolution['width']}",
                f"WAYDROID_MANAGER_HEIGHT={resolution['height']}",
            ))
        wayland_display = graphics_environment.get("GAMESCOPE_WAYLAND_DISPLAY") or graphics_environment.get("WAYLAND_DISPLAY")
        if wayland_display:
            environment.append(f"GAMESCOPE_WAYLAND_DISPLAY={wayland_display}")
            environment.append(f"WAYLAND_DISPLAY={wayland_display}")
        command = [
            "runuser", "-u", user, "--", "env",
            *environment,
            str(self._launcher()), mode,
        ]
        if package:
            command.append(package)
        with log_path.open("a", encoding="utf-8") as log:
            subprocess.Popen(command, env=clean_env(), start_new_session=True, stdout=log, stderr=subprocess.STDOUT)

    def _state_path(self, home: Path) -> Path:
        return home / ".config/waydroid-manager/state.json"

    def _load_state(self, home: Path) -> dict[str, Any]:
        state: dict[str, Any] = {
            "autoAddApps": False,
            "observedApps": [],
            "pendingApps": [],
            "shortcuts": {},
            "removedShortcuts": [],
        }
        try:
            saved = json.loads(self._state_path(home).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return state
        if not isinstance(saved, dict):
            return state
        for key in state:
            if isinstance(saved.get(key), type(state[key])):
                state[key] = saved[key]
        return state

    def _save_state(self, home: Path, state: dict[str, Any]) -> None:
        path = self._state_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        owner = home.stat()
        os.chown(path.parent, owner.st_uid, owner.st_gid)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            json.dump(state, temporary, sort_keys=True)
            temporary_path = Path(temporary.name)
        os.chown(temporary_path, owner.st_uid, owner.st_gid)
        temporary_path.replace(path)

    def _shortcut_ids(self, home: Path) -> dict[str, int]:
        state = self._load_state(home)
        shortcuts = state["shortcuts"]
        if not isinstance(shortcuts, dict):
            return {}
        recorded = {key: value for key, value in shortcuts.items() if isinstance(key, str) and isinstance(value, int)}
        removed = set(state["removedShortcuts"])
        try:
            saved_shortcuts = self._load_shortcuts(self._shortcuts_path(home))
        except (OSError, RuntimeError, ValueError):
            return recorded

        launcher = str(self._launcher())
        names = {"waydroid": WAYDROID_SHORTCUT_KEY}
        directory = home / ".local/share/applications"
        for entry in directory.glob("waydroid.*.desktop"):
            package = entry.stem.removeprefix("waydroid.")
            if not PACKAGE_RE.fullmatch(package):
                continue
            try:
                parser = configparser.ConfigParser(interpolation=None)
                parser.read(entry, encoding="utf-8")
                name = parser.get("Desktop Entry", "Name", fallback="").strip()
            except (OSError, configparser.Error):
                continue
            if name:
                names.setdefault(name.casefold(), package)

        def shortcut_key(options: str) -> str | None:
            if options == "full" or options.endswith(" full"):
                return WAYDROID_SHORTCUT_KEY
            match = re.search(r"(?:^|\s)app\s+([A-Za-z0-9._-]+)$", options)
            return match.group(1) if match and PACKAGE_RE.fullmatch(match.group(1)) else None

        ids: dict[str, int] = {}
        saved_by_id: dict[int, dict[str, tuple[int, Any]]] = {}
        for _, (_, shortcut) in saved_shortcuts.items():
            exe = str(shortcut.get("exe", (1, ""))[1]).strip('"')
            options = str(shortcut.get("LaunchOptions", (1, ""))[1])
            name = str(shortcut.get("appname", (1, ""))[1]).strip().casefold()
            app_id = shortcut.get("appid", (2, 0))[1]
            if not isinstance(app_id, int):
                continue
            normalized_id = app_id & 0xFFFFFFFF
            saved_by_id[normalized_id] = shortcut
            key = shortcut_key(options) if exe == launcher else names.get(name)
            if key is None:
                continue
            if key not in removed:
                ids[key] = normalized_id
        for key, app_id in recorded.items():
            shortcut = saved_by_id.get(app_id & 0xFFFFFFFF)
            if shortcut is None or key in removed:
                continue
            options = str(shortcut.get("LaunchOptions", (1, ""))[1])
            if shortcut_key(options) == key:
                ids[key] = app_id & 0xFFFFFFFF
        return ids

    def _removable_packages(self) -> set[str]:
        try:
            output = self._run(["waydroid", "shell", "--", "pm", "list", "packages", "-3"], timeout=10)
        except (RuntimeError, subprocess.TimeoutExpired):
            return set()
        return {
            line.removeprefix("package:")
            for line in output.splitlines()
            if line.startswith("package:") and PACKAGE_RE.fullmatch(line.removeprefix("package:"))
        }

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
        roots = [
            home / ".local/share/Steam/userdata",
            home / ".steam/steam/userdata",
            home / ".var/app/com.valvesoftware.Steam/data/Steam/userdata",
        ]
        for root in roots:
            paths = sorted(root.glob("*/config/shortcuts.vdf"))
            if paths:
                return paths[0]
        raise RuntimeError("Steam has not created shortcuts.vdf for this user yet")

    def _read_cstring(self, data: bytes, offset: int) -> tuple[str, int]:
        end = data.index(b"\0", offset)
        return data[offset:end].decode("utf-8", errors="replace"), end + 1

    def _read_vdf(self, data: bytes, offset: int = 0) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while offset < len(data):
            value_type = data[offset]
            offset += 1
            if value_type == 8:
                return result, offset
            key, offset = self._read_cstring(data, offset)
            if value_type == 0:
                value, offset = self._read_vdf(data, offset)
            elif value_type == 1:
                value, offset = self._read_cstring(data, offset)
            elif value_type == 2:
                value = struct.unpack_from("<i", data, offset)[0]
                offset += 4
            elif value_type == 7:
                value = struct.unpack_from("<Q", data, offset)[0]
                offset += 8
            else:
                raise RuntimeError(f"Unsupported Steam shortcut field type {value_type}")
            result[key] = (value_type, value)
        raise RuntimeError("Steam shortcuts.vdf ended unexpectedly")

    def _write_vdf(self, items: dict[str, tuple[int, Any]]) -> bytes:
        output = bytearray()
        for key, (value_type, value) in items.items():
            output.append(value_type)
            output.extend(key.encode("utf-8"))
            output.append(0)
            if value_type == 0:
                output.extend(self._write_vdf(value))
            elif value_type == 1:
                output.extend(str(value).encode("utf-8"))
                output.append(0)
            elif value_type == 2:
                output.extend(struct.pack("<i", value))
            elif value_type == 7:
                output.extend(struct.pack("<Q", value))
            else:
                raise RuntimeError(f"Unsupported Steam shortcut field type {value_type}")
        output.append(8)
        return bytes(output)

    def _load_shortcuts(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        root, _ = self._read_vdf(path.read_bytes())
        if "shortcuts" not in root or root["shortcuts"][0] != 0:
            raise RuntimeError("Steam shortcuts.vdf has an unexpected format")
        return root["shortcuts"][1]

    def _save_shortcuts(self, path: Path, shortcuts: dict[str, Any]) -> None:
        payload = self._write_vdf({"shortcuts": (0, shortcuts)})
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)

    def _remove_shortcuts(self, home: Path) -> None:
        try:
            path = self._shortcuts_path(home)
        except RuntimeError:
            return
        shortcuts = self._load_shortcuts(path)
        launcher = f'"{self._launcher()}"'
        removed = [key for key, (_, item) in shortcuts.items() if item.get("exe", (1, ""))[1] == launcher]
        for key in removed:
            del shortcuts[key]
        if removed:
            self._save_shortcuts(path, shortcuts)
            owner = home.stat()
            os.chown(path, owner.st_uid, owner.st_gid)

    async def get_status(self) -> dict[str, Any]:
        _, _, home = self._user()
        state = self._load_state(home)
        shortcut_ids = self._shortcut_ids(home)
        return {
            "initialized": self._initialized(),
            "serviceRunning": self._service_state("active"),
            "gamescopeInstalled": shutil.which("gamescope") is not None,
            "resolution": self._panel_resolution(),
            "autoAddApps": state["autoAddApps"],
            "waydroidShortcutId": shortcut_ids.get(WAYDROID_SHORTCUT_KEY),
        }

    async def list_apps(self) -> list[dict[str, Any]]:
        return self._desktop_entries(self._removable_packages()) if self._initialized() else []

    def _shortcut_details(self, name: str, package: str | None = None, icon: str = "") -> dict[str, str]:
        _, _, home = self._user()
        return {
            "name": name,
            "exe": str(self._launcher()),
            "startDir": str(home),
            "launchOptions": f"{LAUNCH_WRAPPER} %command% " + ("full" if package is None else f"app {package}"),
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
        state = self._load_state(home)
        state["shortcuts"][key] = app_id
        state["removedShortcuts"] = [item for item in state["removedShortcuts"] if item != key]
        state["pendingApps"] = [item for item in state["pendingApps"] if item != key]
        self._save_state(home, state)

    async def remove_shortcut_record(self, key: str) -> None:
        self._validate_shortcut_key(key)
        _, _, home = self._user()
        state = self._load_state(home)
        state["shortcuts"].pop(key, None)
        state["pendingApps"] = [item for item in state["pendingApps"] if item != key]
        if key not in state["removedShortcuts"]:
            state["removedShortcuts"].append(key)
        self._save_state(home, state)

    async def set_auto_add_apps(self, enabled: bool) -> None:
        _, _, home = self._user()
        state = self._load_state(home)
        state["autoAddApps"] = enabled
        if enabled:
            state["observedApps"] = sorted({*state["observedApps"], *(app["package"] for app in self._desktop_entries())})
        self._save_state(home, state)

    async def pending_auto_shortcuts(self) -> list[dict[str, str]]:
        _, _, home = self._user()
        state = self._load_state(home)
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

    async def get_shortcut_artwork(self, key: str, app_id: int) -> dict[str, Any]:
        self._validate_shortcut_key(key)
        _, _, home = self._user()
        if self._shortcut_ids(home).get(key) != app_id:
            raise RuntimeError("The Steam shortcut no longer exists")
        roles = missing_artwork(self._shortcuts_path(home).parent / "grid", app_id)
        app = next((item for item in self._desktop_entries() if item["package"] == key), None)
        result = {"roles": roles, "ready": not app, "name": app["name"] if app else "Waydroid", "icon": app["icon"] if app else "", "images": []}
        if not roles or not app or not self._service_state("active"):
            return result
        try:
            pid = self._run(["lxc-info", "-P", "/var/lib/waydroid/lxc", "-n", "waydroid", "-pH"])
            if not pid.isdecimal():
                return result
            root = (Path("/proc") / pid / "root").resolve(strict=True)
            paths = self._run(["waydroid", "shell", "--", "pm", "path", key]).splitlines()
            apks = []
            for path in paths:
                if not path.startswith("package:/"):
                    continue
                apk = (root / path.removeprefix("package:/")).resolve(strict=True)
                apk.relative_to(root)
                if apk.suffix == ".apk":
                    apks.append(apk)
            result["ready"] = bool(apks)
            result["images"] = await asyncio.to_thread(apk_images, apks)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, subprocess.SubprocessError):
            pass
        return result

    async def install_gapps(self) -> None:
        if self._initialized():
            raise RuntimeError("Waydroid is already initialized. Remove it before installing a new image.")
        self._run(["waydroid", "init", "--system_type", "GAPPS"], timeout=1800)

    def _install_file(self, value: str) -> Path:
        _, _, home = self._user()
        try:
            path = Path(value).resolve(strict=True)
            path.relative_to(home)
        except (OSError, ValueError):
            raise RuntimeError("Select an APK or XAPK from your home folder")
        if not path.is_file() or path.suffix.lower() not in {".apk", ".xapk"}:
            raise RuntimeError("Select a valid APK or XAPK file")
        return path

    def _require_session(self) -> None:
        try:
            status = self._run(["waydroid", "status"])
        except RuntimeError as error:
            raise RuntimeError("Start Waydroid before installing an app") from error
        if not re.search(r"^Session:\s*RUNNING$", status, re.MULTILINE):
            raise RuntimeError("Start Waydroid before installing an app")

    async def install_package(self, value: str) -> None:
        if not self._initialized():
            raise RuntimeError("Install the GAPPS image before installing apps")
        path = self._install_file(value)
        self._require_session()
        if path.suffix.lower() == ".apk":
            self._run(["waydroid", "app", "install", str(path)], timeout=300)
            return

        _, _, home = self._user()
        host_dir = home / ".local/share/waydroid/data/waydroid_tmp" / f"decky-{uuid.uuid4().hex}"
        try:
            with zipfile.ZipFile(path) as archive:
                packages = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".apk")]
                if not packages:
                    raise RuntimeError("This XAPK does not contain any APK files")
                host_dir.mkdir(parents=True)
                installed: list[str] = []
                for index, item in enumerate(packages):
                    name = Path(item.filename).name
                    if not name or name in installed:
                        raise RuntimeError("This XAPK contains invalid APK names")
                    target = host_dir / name
                    with archive.open(item) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    installed.append(name)
            guest_dir = f"/data/waydroid_tmp/{host_dir.name}"
            self._run(["waydroid", "shell", "--", "pm", "install-multiple", "-r", *[f"{guest_dir}/{name}" for name in installed]], timeout=300)
        except zipfile.BadZipFile as error:
            raise RuntimeError("This XAPK is not a valid archive") from error
        finally:
            shutil.rmtree(host_dir, ignore_errors=True)

    async def start_service(self) -> None:
        self._run(["systemctl", "start", SERVICE])

    async def stop_service(self) -> None:
        self._run(["systemctl", "stop", SERVICE])

    async def restart_service(self) -> None:
        self._run(["systemctl", "restart", SERVICE])

    async def launch_waydroid(self) -> None:
        self._start_launcher("full")

    async def launch_app(self, package: str) -> None:
        if not PACKAGE_RE.fullmatch(package):
            raise RuntimeError("Invalid Android package name")
        self._start_launcher("app", package)

    async def uninstall_app(self, package: str) -> None:
        if not PACKAGE_RE.fullmatch(package):
            raise RuntimeError("Invalid Android package name")
        if package not in self._removable_packages():
            raise RuntimeError("This Android app is not removable")
        self._run(["waydroid", "app", "remove", package], timeout=60)

    async def remove_waydroid(self) -> None:
        user, _, home = self._user()
        subprocess.run(["systemctl", "disable", "--now", SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        subprocess.run(["waydroid", "session", "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        shutil.rmtree(WAYDROID_DIR, ignore_errors=True)
        shutil.rmtree(home / ".local/share/waydroid", ignore_errors=True)
        for entry in (home / ".local/share/applications").glob("waydroid.*.desktop"):
            entry.unlink(missing_ok=True)
        self._remove_shortcuts(home)
        self._state_path(home).unlink(missing_ok=True)
        decky.logger.info("Removed Waydroid data for %s", user)

    async def _main(self):
        self._frame_limiter = FrameLimiter(self._run)
        self._frame_limit_lock = asyncio.Lock()
        await asyncio.to_thread(self._start_input_sync)
        decky.logger.info("Waydroid Manager loaded")

    async def _unload(self):
        try:
            async with self._frame_limit_lock:
                await asyncio.to_thread(self._frame_limiter.restore)
        finally:
            await asyncio.to_thread(self._stop_input_sync)

    async def sync_frame_limit(self, fps: int) -> None:
        if type(fps) is not int or not 0 <= fps <= 1000:
            raise RuntimeError("Invalid frame limit")
        async with self._frame_limit_lock:
            _, uid, _ = self._user()
            relay = Path(decky.DECKY_PLUGIN_DIR).resolve() / "bin/waydroid-wayland-relay"
            launch = await asyncio.to_thread(active_launch, uid, relay)
            await asyncio.to_thread(self._frame_limiter.sync, fps, launch)
