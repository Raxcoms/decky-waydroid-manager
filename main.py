import asyncio
import configparser
import os
import pwd
import re
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Any

import decky


PACKAGE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
WAYDROID_DIR = Path("/var/lib/waydroid")
SERVICE = "waydroid-container.service"


class Plugin:
    def _run(self, command: list[str], timeout: int = 30) -> str:
        result = subprocess.run(
            command,
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
        home = Path(getattr(decky, "DECKY_USER_HOME", ""))
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
        return {"width": width, "height": height}

    def _launcher(self) -> Path:
        path = Path(decky.DECKY_PLUGIN_DIR) / "bin" / "waydroid-launcher"
        if not path.is_file():
            raise RuntimeError("The bundled Waydroid launcher is missing")
        return path

    def _start_launcher(self, mode: str, package: str | None = None) -> None:
        if not self._initialized():
            raise RuntimeError("Install the GAPPS image before starting Waydroid")
        if not shutil.which("gamescope"):
            raise RuntimeError("Gamescope is unavailable in this ArmadaOS deployment. Update or repair the deployment before launching Waydroid.")
        self._run(["systemctl", "start", SERVICE])
        user, uid, home = self._user()
        command = ["runuser", "-u", user, "--", "env", f"HOME={home}", f"XDG_RUNTIME_DIR=/run/user/{uid}", str(self._launcher()), mode]
        if package:
            command.append(package)
        subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _desktop_entries(self) -> list[dict[str, str]]:
        _, _, home = self._user()
        directory = home / ".local/share/applications"
        apps: list[dict[str, str]] = []
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
                apps.append({
                    "name": data.get("Name", package),
                    "package": package,
                    "icon": data.get("Icon", ""),
                })
            except (OSError, KeyError, configparser.Error):
                continue
        return apps

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

    def _shortcut(self, name: str, package: str | None = None) -> bool:
        user, _, home = self._user()
        path = self._shortcuts_path(home)
        shortcuts = self._load_shortcuts(path)
        launcher = str(self._launcher())
        options = "full" if package is None else f"app {package}"
        executable = f'"{launcher}"'
        for _, (_, item) in shortcuts.items():
            if item.get("exe", (1, ""))[1] == executable and item.get("LaunchOptions", (1, ""))[1] == options:
                return False
        indexes = [int(key) for key in shortcuts if key.isdigit()]
        index = str(max(indexes, default=-1) + 1)
        app_id = zlib.crc32((executable + options).encode("utf-8")) | 0x80000000
        if app_id >= 0x80000000:
            app_id -= 0x100000000
        shortcuts[index] = (0, {
            "appid": (2, app_id),
            "appname": (1, name),
            "exe": (1, executable),
            "StartDir": (1, f'"{home}"'),
            "icon": (1, ""),
            "ShortcutPath": (1, ""),
            "LaunchOptions": (1, options),
            "IsHidden": (2, 0),
            "AllowDesktopConfig": (2, 1),
            "AllowOverlay": (2, 1),
            "OpenVR": (2, 0),
            "Devkit": (2, 0),
            "DevkitGameID": (1, ""),
            "LastPlayTime": (2, 0),
            "tags": (0, {"0": (1, "Waydroid")}),
        })
        self._save_shortcuts(path, shortcuts)
        os.chown(path, pwd.getpwnam(user).pw_uid, pwd.getpwnam(user).pw_gid)
        return True

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
        return {
            "initialized": self._initialized(),
            "serviceRunning": self._service_state("active"),
            "autoStart": self._service_state("enabled"),
            "gamescopeInstalled": shutil.which("gamescope") is not None,
            "resolution": self._panel_resolution(),
        }

    async def list_apps(self) -> list[dict[str, str]]:
        return self._desktop_entries() if self._initialized() else []

    async def install_gapps(self) -> None:
        if self._initialized():
            raise RuntimeError("Waydroid is already initialized. Remove it before installing a new image.")
        self._run(["waydroid", "init", "--system_type", "GAPPS"], timeout=1800)

    async def set_auto_start(self, enabled: bool) -> None:
        self._run(["systemctl", "enable" if enabled else "disable", SERVICE])

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

    async def add_waydroid_shortcut(self) -> bool:
        return self._shortcut("Waydroid")

    async def add_app_shortcut(self, package: str, name: str) -> bool:
        if not PACKAGE_RE.fullmatch(package):
            raise RuntimeError("Invalid Android package name")
        return self._shortcut(name, package)

    async def remove_waydroid(self) -> None:
        user, _, home = self._user()
        subprocess.run(["systemctl", "disable", "--now", SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        subprocess.run(["waydroid", "session", "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        shutil.rmtree(WAYDROID_DIR, ignore_errors=True)
        shutil.rmtree(home / ".local/share/waydroid", ignore_errors=True)
        for entry in (home / ".local/share/applications").glob("waydroid.*.desktop"):
            entry.unlink(missing_ok=True)
        self._remove_shortcuts(home)
        decky.logger.info("Removed Waydroid data for %s", user)

    async def _main(self):
        decky.logger.info("Waydroid Manager loaded")
