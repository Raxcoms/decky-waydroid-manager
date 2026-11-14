"""Fetch pinned upstream build inputs into a cache outside the repository."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tempfile
import urllib.request


def file_digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def fetch(entry: dict, cache: Path) -> Path:
    if (not re.fullmatch(r"[a-zA-Z0-9_-]+", entry["name"])
            or not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", ""))
            or not entry["url"].startswith("https://")):
        raise RuntimeError("Invalid pinned dependency")
    archive = cache / f"{entry['name']}-{entry['sha256'][:16]}.tar.gz"
    cache.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        with tempfile.NamedTemporaryFile(dir=cache, suffix=".part", delete=False) as file:
            temporary = Path(file.name)
        try:
            with urllib.request.urlopen(entry["url"], timeout=60) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            if file_digest(temporary) != entry["sha256"]:
                raise RuntimeError(f"Dependency checksum mismatch: {entry['name']}")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    if file_digest(archive) != entry["sha256"]:
        raise RuntimeError(f"Dependency checksum mismatch: {entry['name']}")
    return archive


def extract(archive: Path, destination: Path, strip_root: bool = False, exclude: tuple[str, ...] = ()) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        root = Path(temporary)
        _extract(archive, root, strip_root, exclude)
        root.rename(destination)


def _extract(archive: Path, root: Path, strip_root: bool, exclude: tuple[str, ...]) -> None:
    with tarfile.open(archive) as source:
        members = []
        for member in source.getmembers():
            path = Path(member.name)
            if strip_root:
                path = Path(*path.parts[1:])
            if path.as_posix() in exclude:
                continue
            member.name = path.as_posix()
            if not (root / path).resolve().is_relative_to(root) or member.isdev():
                raise RuntimeError("Unsafe dependency archive entry")
            if member.issym() or member.islnk():
                if member.islnk() and strip_root:
                    member.linkname = Path(*Path(member.linkname).parts[1:]).as_posix()
                target = path.parent / member.linkname if member.issym() else Path(member.linkname)
                if not (root / target).resolve().is_relative_to(root):
                    raise RuntimeError("Unsafe dependency archive link")
            members.append(member)
        source.extractall(root, members=members)


def prepare(profile: Path, cache: Path, output: Path) -> dict:
    metadata = json.loads(profile.read_text())
    for entry in metadata["dependencies"]:
        target = output / entry["path"]
        if not target.resolve().is_relative_to(output.resolve()):
            raise RuntimeError("Dependency source path escapes the build directory")
        if target.exists():
            marker = target / ".waydroid-dependency"
            if target.is_symlink() or not marker.is_file() or marker.read_text().strip() != entry["sha256"]:
                raise RuntimeError(f"Dependency directory is not a verified cache entry: {entry['name']}")
            continue
        print(f"Fetching {entry['name']}", flush=True)
        archive = fetch(entry, cache)
        extract(archive, target, entry.get("stripRoot", False), tuple(entry.get("exclude", [])))
        (target / ".waydroid-dependency").write_text(entry["sha256"] + "\n")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.profile, args.cache, args.output)
