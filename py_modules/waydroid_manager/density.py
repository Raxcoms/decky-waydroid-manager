import configparser
from pathlib import Path
import re
import subprocess
import tempfile

from .proc import clean_env


CONFIG = "system/product/etc/displayconfig/default.xml"


def _image_configuration(images: Path, image: str, path: str, run) -> bytes:
    with tempfile.TemporaryDirectory(prefix="waydroid-density-") as directory:
        target = Path(directory) / "display.xml"
        run(["debugfs", "-R", f"dump {path} {target}", str(images / image)], timeout=10)
        if not target.exists():
            return b""
        if target.stat().st_size > 1024 * 1024:
            raise RuntimeError("The image's display configuration is too large")
        return target.read_bytes()


def prepare_density(config_dir: Path, overlay: Path, reference: tuple[int, int, int], run) -> None:
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_dir / "waydroid.cfg")
    # Keep an explicit user density setting in charge.
    if any(config.has_option("properties", key) for key in ("ro.sf.lcd_density", "qemu.sf.lcd_density")):
        return
    images = Path(config.get("waydroid", "images_path"))
    width, height, dpi = reference
    for image, path in (("system.img", "/system/etc/prop.default"),
                        ("system.img", "/system/build.prop"),
                        ("vendor.img", "/build.prop"),
                        ("system.img", "/product/build.prop"),
                        ("system.img", "/system/product/build.prop")):
        properties = run(["debugfs", "-R", f"cat {path}", str(images / image)], timeout=10)
        values = dict(re.findall(r"^((?:ro|qemu)\.sf\.lcd_density)\s*=\s*(\d+)\s*$", properties, re.MULTILINE))
        value = values.get("qemu.sf.lcd_density", values.get("ro.sf.lcd_density", ""))
        if value and 1 <= int(value) <= 32767:
            dpi = int(value)
    source = b""
    locations = ((CONFIG, (("system.img", "/product/etc/displayconfig/default.xml"),
                           ("system.img", "/system/product/etc/displayconfig/default.xml"))),
                 ("vendor/etc/displayconfig/default.xml", (("vendor.img", "/etc/displayconfig/default.xml"),)),
                 ("system/etc/displayconfig/default.xml", (("system.img", "/system/etc/displayconfig/default.xml"),)))
    for relative, image_paths in locations:
        existing = config_dir / "overlay" / relative
        if existing.exists():
            if existing.is_symlink() or not existing.is_file() or existing.stat().st_size > 1024 * 1024:
                raise RuntimeError("Invalid existing display density configuration")
            source = existing.read_bytes()
            break
        for image, path in image_paths:
            source = _image_configuration(images, image, path, run)
            if source:
                break
        if source:
            break
    content = subprocess.check_output(["/usr/bin/python3", "-I", str(Path(__file__).with_name("density_settings.py")),
                                       str(width), str(height), str(dpi)], input=source, env=clean_env(), timeout=5)
    target = overlay / CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    target.chmod(0o644)
