import configparser
from pathlib import Path
import shutil


def images_directory(config: Path) -> Path:
    settings = configparser.ConfigParser(interpolation=None)
    settings.read(config / "waydroid.cfg")
    return Path(settings.get("waydroid", "images_path"))


def extract(config: Path, image: str, paths: tuple[str, ...], target: Path, run, *, missing_ok: bool = False) -> Path:
    for path in paths:
        relative = Path(path.removeprefix("/"))
        existing = config / "overlay" / (Path("vendor") / relative if image == "vendor.img" else relative)
        if existing.is_symlink() or existing.exists():
            if existing.is_symlink() or not existing.is_file() or existing.stat().st_size > 64 * 1024 * 1024:
                raise RuntimeError("Invalid existing Android resource override")
            shutil.copyfile(existing, target)
        else:
            run(["debugfs", "-R", f"dump {path} {target}", str(images_directory(config) / image)], timeout=15)
        if target.is_file():
            if target.stat().st_size > 64 * 1024 * 1024:
                raise RuntimeError("Android image resource is too large")
            return target
    if not missing_ok:
        raise RuntimeError(f"The Android image does not provide {target.name}")
    return target
