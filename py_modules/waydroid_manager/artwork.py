import hashlib
from pathlib import Path
import re
import stat


ARTWORK_TYPES = {"portrait": (0, "p"), "hero": (1, "_hero"), "logo": (2, "_logo"), "landscape": (3, "")}
MAX_TOTAL_BYTES = 12 * 1024 * 1024
ARTWORK_FILE = re.compile(r"(\d{1,10})(?:(?:_hero|_logo|p)?\.png|\.json)")
ARTWORK_RECORD = re.compile(r"(?:[1-9]\d{0,2}:)?[0-9a-f]{64}")
ARTWORK_VERSION = 6


def artwork_filename(app_id: int, role: str) -> str:
    if role == "logoPosition":
        return f"{app_id}.json"
    return f"{app_id}{ARTWORK_TYPES[role][1]}.png"


def _matches_record(path: Path, record: str) -> bool:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_TOTAL_BYTES:
        return False
    with path.open("rb") as file:
        digest = hashlib.sha256(file.read(MAX_TOTAL_BYTES + 1)).hexdigest()
    after = path.lstat()
    return digest == record.rsplit(":", 1)[-1] and (after.st_ino, after.st_ctime_ns) == (before.st_ino, before.st_ctime_ns)

def _slot_images(grid: Path, app_id: int, suffix: str) -> list[Path]:
    stem = f"{app_id & 0xFFFFFFFF}{suffix}"
    return [path for path in grid.glob(f"{stem}.*") if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]


def artwork_attached(grid: Path, app_id: int) -> bool:
    return all(any(path.is_file() and path.stat().st_size for path in _slot_images(grid, app_id, suffix))
               for role, (_, suffix) in ARTWORK_TYPES.items() if role != "logo")


def artwork_updates(home: Path, grid: Path, app_id: int, recorded: dict[str, str]) -> tuple[list[str], bool]:
    home, grid = home.resolve(), grid.resolve()
    if not grid.is_relative_to(home):
        return [], False
    roles = []
    clear_logo = False
    for role, (_, suffix) in ARTWORK_TYPES.items():
        stem = f"{app_id & 0xFFFFFFFF}{suffix}"
        existing = _slot_images(grid, app_id, suffix)
        if not existing:
            if role != "logo":
                roles.append(role)
            continue
        path = grid / f"{stem}.png"
        record = recorded.get(str(path.relative_to(home)))
        if existing != [path] or not record:
            continue
        version, separator, _ = record.partition(":")
        if separator and int(version) >= ARTWORK_VERSION:
            continue
        # Update only untouched artwork recorded by an older generator.
        try:
            if _matches_record(path, record):
                if role == "logo":
                    clear_logo = True
                else:
                    roles.append(role)
        except OSError:
            continue
    return roles, clear_logo


def prune_artwork(home: Path, grid: Path, recorded: dict[str, str], live_ids: set[int]) -> None:
    grid = grid.resolve()
    if not grid.is_relative_to(home.resolve()):
        return
    for relative, digest in list(recorded.items()):
        path = home / relative
        if path.parent != grid or not (match := ARTWORK_FILE.fullmatch(path.name)) or int(match[1]) in live_ids:
            continue
        try:
            if _matches_record(path, digest):
                path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            continue
        recorded.pop(relative)
