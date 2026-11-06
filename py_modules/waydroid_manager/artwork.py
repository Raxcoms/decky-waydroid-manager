import base64
from pathlib import Path
import re
import zipfile


ARTWORK_TYPES = {"portrait": (0, "p"), "hero": (1, "_hero"), "logo": (2, "_logo"), "landscape": (3, "")}
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
IMAGE_NAME = re.compile(r"(?:banner|logo|splash|cover|hero|background|homescreen).+\.(?:png|webp|jpe?g)$|(?:banner|logo|splash|cover|hero|background)\.(?:png|webp|jpe?g)$", re.I)
SDK_NAME = re.compile(r"(?:google|facebook|applovin|mbridge|bigo|admob|unityads|ironsource|bytedance|tiktok|common_google|notification|billing|sentry)", re.I)


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
