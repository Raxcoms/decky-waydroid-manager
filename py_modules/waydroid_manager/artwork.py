import base64
import hashlib
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


ARTWORK_TYPES = {"portrait": (0, "p"), "hero": (1, "_hero"), "logo": (2, "_logo"), "landscape": (3, "")}
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
IMAGE_NAME = re.compile(r"(?:banner|logo|splash|cover|hero|background|homescreen|icon|ic_launcher)[^/]*\.(?:png|webp|jpe?g)$", re.I)
SDK_NAME = re.compile(r"(?:google|facebook|applovin|mbridge|bigo|admob|unityads|ironsource|bytedance|tiktok|common_google|notification|billing|sentry)", re.I)
ARTWORK_FILE = re.compile(r"(\d{1,10})(?:(?:_hero|_logo|p)?\.png|\.json)")


def artwork_filename(app_id: int, role: str) -> str:
    if role == "logoPosition":
        return f"{app_id}.json"
    return f"{app_id}{ARTWORK_TYPES[role][1]}.png"


def prune_artwork(home: Path, grid: Path, recorded: dict[str, str], live_ids: set[int]) -> None:
    grid = grid.resolve()
    if not grid.is_relative_to(home.resolve()):
        return
    for relative, digest in list(recorded.items()):
        path = home / relative
        if path.parent != grid or not (match := ARTWORK_FILE.fullmatch(path.name)) or int(match[1]) in live_ids:
            continue
        try:
            before = path.lstat()
            if stat.S_ISREG(before.st_mode) and before.st_size <= MAX_TOTAL_BYTES:
                with path.open("rb") as file:
                    matches = hashlib.file_digest(file, "sha256").hexdigest() == digest
                after = path.lstat()
                if matches and (after.st_ino, after.st_ctime_ns) == (before.st_ino, before.st_ctime_ns):
                    path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            continue
        recorded.pop(relative)


def persistent_apks(data: Path, package: str) -> list[Path]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", package):
        return []
    root = (data / "app").resolve()
    directories = []
    for pattern in (f"{package}-*", f"*/{package}-*"):
        for directory in root.glob(pattern):
            directory = directory.resolve()
            if directory.is_relative_to(root) and (directory / "base.apk").is_file():
                directories.append(directory)
    if not directories:
        return []
    directory = max(directories, key=lambda path: path.stat().st_mtime_ns)
    return [path for path in sorted(directory.glob("*.apk"))
            if path.resolve().is_relative_to(directory) and path.is_file()][:64]


def package_apks(root: Path, output: str) -> list[Path]:
    apks = []
    for line in output.splitlines():
        if not line.startswith("package:/"):
            continue
        relative = PurePosixPath(line.removeprefix("package:/"))
        if ".." not in relative.parts and not relative.is_absolute() and relative.suffix == ".apk":
            apks.append(root / relative)
    return apks


def missing_artwork(grid: Path, app_id: int) -> list[str]:
    return [role for role, (_, suffix) in ARTWORK_TYPES.items()
            if not any(path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                       for path in grid.glob(f"{app_id & 0xFFFFFFFF}{suffix}.*"))]


def apk_images(apks: list[Path]) -> list[dict[str, str]]:
    images = []
    total = 0
    for apk in apks:
        with zipfile.ZipFile(apk) as archive:
            candidates = [info for info in archive.infolist()
                          if IMAGE_NAME.search(info.filename) and not SDK_NAME.search(info.filename)
                          and 1024 <= info.file_size <= MAX_IMAGE_BYTES]
            candidates.sort(key=lambda info: (not info.filename.startswith("assets/"), -info.file_size))
            for info in candidates:
                if len(images) >= 16 or total + info.file_size > MAX_TOTAL_BYTES:
                    continue
                data = archive.read(info)
                mime = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[Path(info.filename).suffix.lower()]
                images.append({"name": info.filename, "data": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")})
                total += len(data)
    return images
