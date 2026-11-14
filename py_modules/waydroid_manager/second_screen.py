from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import stat


DISPLAY_VARIABLE = "WAYDROID_MANAGER_EXTERNAL_WAYLAND_DISPLAY"
ENVIRONMENT_VARIABLE = "WAYDROID_MANAGER_EXTERNAL_WAYLAND_ENV"


@dataclass(frozen=True)
class ExternalDisplay:
    socket: Path


def _display_path(value: str, runtime: Path) -> Path | None:
    if not value or "\x00" in value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = runtime / path
    try:
        return path.resolve(strict=True)
    except OSError:
        return None


def _environment_display(path: Path, uid: int) -> str | None:
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "r", encoding="utf-8") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_size > 65536:
                return None
            lines = file.read(65537).splitlines()
    except (OSError, UnicodeError):
        return None
    result = None
    for line in lines:
        name, separator, value = line.partition("=")
        if name != "WAYLAND_DISPLAY" or not separator:
            continue
        try:
            values = shlex.split(value, posix=True)
        except ValueError:
            return None
        if len(values) == 1:
            result = values[0]
    return result


def _socket(path: Path, uid: int) -> ExternalDisplay | None:
    try:
        info = path.stat()
    except OSError:
        return None
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid:
        return None
    return ExternalDisplay(path)


def discover_external_display(uid: int, environment: dict[str, str] | None = None,
                              runtime: Path | None = None, primary: Path | None = None) -> ExternalDisplay | None:
    """Find a host-provided secondary Wayland socket without identifying a device."""
    environment = os.environ if environment is None else environment
    runtime = runtime or Path(f"/run/user/{uid}")
    candidates: list[str] = []
    if display := environment.get(DISPLAY_VARIABLE):
        candidates.append(display)

    if environment_file := environment.get(ENVIRONMENT_VARIABLE):
        path = Path(environment_file)
        if display := _environment_display(path, uid):
            candidates.append(display)

    # Host integrations can publish an environment snapshot for their output.
    try:
        environment_files = sorted(runtime.glob("*-env"))
    except OSError:
        environment_files = []
    for path in environment_files:
        if display := _environment_display(path, uid):
            candidates.append(display)

    for value in candidates:
        if path := _display_path(value, runtime):
            if primary is not None and path == primary.resolve():
                continue
            if display := _socket(path, uid):
                return display
    return None
