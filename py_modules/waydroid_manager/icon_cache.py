import base64
import hashlib
import os
from pathlib import Path
import re
import stat
import struct
import tempfile


MAX_ICON_BYTES = 1024 * 1024


def source_digest(icon: str) -> str:
    return hashlib.sha256(icon.encode()).hexdigest()


class IconCache:
    def __init__(self, home: Path):
        self.home = home.resolve()
        self.directory = home / ".cache/waydroid-manager/icons"

    def path(self, package: str, source: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", package) or not re.fullmatch(r"[0-9a-f]{64}", source):
            raise ValueError("Invalid icon cache key")
        key = hashlib.sha256((package + "\0" + source).encode()).hexdigest()
        return self.directory / f"{key}.png"

    @staticmethod
    def validate(content: bytes) -> None:
        if (len(content) > MAX_ICON_BYTES or len(content) < 45 or content[:8] != b"\x89PNG\r\n\x1a\n"
                or content[12:16] != b"IHDR" or content[-12:] != b"\0\0\0\0IEND\xaeB`\x82"
                or struct.unpack_from(">II", content, 16) != (512, 512)):
            raise ValueError("Invalid high-resolution app icon")

    def get(self, package: str, source: str) -> str | None:
        path = self.path(package, source)
        try:
            if not path.resolve().is_relative_to(self.home):
                return None
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as file:
                info = os.fstat(file.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ICON_BYTES
                        or info.st_uid != self.home.stat().st_uid):
                    return None
                content = file.read(MAX_ICON_BYTES + 1)
            self.validate(content)
        except (OSError, ValueError):
            return None
        return "data:image/png;base64," + base64.b64encode(content).decode("ascii")

    def put(self, package: str, source: str, content: bytes) -> None:
        self.validate(content)
        path = self.path(package, source)
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.directory.resolve().is_relative_to(self.home):
            raise ValueError("The icon cache is outside the user home")
        with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
