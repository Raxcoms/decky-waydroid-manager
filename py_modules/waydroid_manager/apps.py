import configparser
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterator


PACKAGE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_DESKTOP_BYTES = 64 * 1024


@dataclass(frozen=True)
class AppExport:
    package: str
    name: str
    icon: str


def app_exports(home: Path, package: str | None = None, *, data_home: Path | None = None) -> Iterator[AppExport]:
    if package is not None and not PACKAGE_RE.fullmatch(package):
        return
    directory = (data_home or home / ".local/share") / "applications"
    entries = (directory / f"waydroid.{package}.desktop",) if package else directory.glob("waydroid.*.desktop")
    for entry in entries:
        package_name = entry.stem.removeprefix("waydroid.")
        if not PACKAGE_RE.fullmatch(package_name):
            continue
        try:
            if entry.is_symlink() or not entry.is_file() or entry.stat().st_size > MAX_DESKTOP_BYTES:
                continue
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(entry, encoding="utf-8")
            data = parser["Desktop Entry"]
            if data.get("Exec") == f"waydroid app launch {package_name}":
                yield AppExport(package_name, data.get("Name", package_name), data.get("Icon", ""))
        except (OSError, KeyError, UnicodeError, configparser.Error):
            continue
