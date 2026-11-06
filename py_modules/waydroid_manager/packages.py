from pathlib import Path
import shutil
import zipfile


MAX_SPLITS = 128


def apk_members(archive: zipfile.ZipFile, suffix: str) -> list[tuple[zipfile.ZipInfo, str]]:
    if suffix == ".apk":
        if "AndroidManifest.xml" not in archive.namelist():
            raise RuntimeError("INVALID_APK_MANIFEST")
        return []
    packages = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".apk")]
    if not packages:
        raise RuntimeError("XAPK_NO_APKS")
    if len(packages) > MAX_SPLITS:
        raise RuntimeError("XAPK_TOO_MANY_APKS")
    names = [Path(item.filename).name for item in packages]
    if any(not name or "\\" in name for name in names) or len(set(names)) != len(names):
        raise RuntimeError("XAPK_INVALID_NAMES")
    return list(zip(packages, names))


def stage_apks(archive: zipfile.ZipFile, members: list[tuple[zipfile.ZipInfo, str]], directory: Path) -> list[str]:
    size = sum(item.file_size for item, _ in members) if members else Path(archive.filename).stat().st_size
    if size > shutil.disk_usage(directory.parent).free:
        raise RuntimeError("PACKAGE_NO_SPACE")
    directory.mkdir()
    if not members:
        archive.fp.seek(0)
        with (directory / "base.apk").open("wb") as destination:
            shutil.copyfileobj(archive.fp, destination)
        return ["base.apk"]
    for item, name in members:
        with archive.open(item) as source, (directory / name).open("wb") as destination:
            shutil.copyfileobj(source, destination)
    return [name for _, name in members]
