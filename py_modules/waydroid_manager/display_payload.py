import configparser
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import tempfile

from .elf_symbols import dynamic_symbols
from .image_files import extract


HWC_PATH = "lib64/hw/hwcomposer.waydroid.so"


@dataclass(frozen=True)
class VendorIdentity:
    fingerprint: str
    sdk: int
    composer_digest: str
    machine: int
    adapter_digest: str = ""
    system_ui_digest: str = ""
    vndk: str = ""
    runtime_symbols: frozenset[str] = frozenset()
    binder_vtable_size: int = 0
    framework_digest: str = ""


def elf_machine(path: Path) -> int:
    with path.open("rb") as file:
        header = file.read(20)
    if len(header) != 20 or header[:6] != b"\x7fELF\x02\x01":
        raise RuntimeError("The external display composer is not a 64-bit Android ELF library")
    return struct.unpack_from("<H", header, 18)[0]


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inspect_vendor(config_dir: Path, run) -> VendorIdentity:
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_dir / "waydroid.cfg")
    image = Path(config.get("waydroid", "images_path")) / "vendor.img"
    if not image.is_file():
        raise RuntimeError("The installed Waydroid vendor image is missing")
    properties = run(["debugfs", "-R", "cat /build.prop", str(image)], timeout=10)
    values = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
    fingerprint = values.get("ro.vendor.build.fingerprint", "")
    sdk = values.get("ro.vendor.build.version.sdk", "")
    vndk = values.get("ro.vndk.version", "")
    if not fingerprint or not sdk.isdecimal() or not vndk:
        raise RuntimeError("Could not identify the installed Waydroid vendor ABI")
    with tempfile.TemporaryDirectory(prefix="waydroid-manager-vendor-") as directory:
        library = Path(directory) / "composer.so"
        run(["debugfs", "-R", f"dump /{HWC_PATH} {library}", str(image)], timeout=15)
        adapter = Path(directory) / "adapter.so"
        run(["debugfs", "-R", f"dump /lib64/libhwc2on1adapter.so {adapter}", str(image)], timeout=15)
        system_ui = Path(directory) / "SystemUI.apk"
        extract(config_dir, "system.img", ("/system_ext/priv-app/SystemUI/SystemUI.apk",
                "/system/system_ext/priv-app/SystemUI/SystemUI.apk"), system_ui, run)
        framework = extract(config_dir, "system.img", ("/system/framework/framework-res.apk",),
                            Path(directory) / "framework-res.apk", run)
        runtime = Path(directory) / "libhidlbase.so"
        for path in ("/system/apex/com.android.vndk.current/lib64/libhidlbase.so",
                     f"/system/apex/com.android.vndk.v{vndk}/lib64/libhidlbase.so",
                     f"/system/lib64/vndk-{vndk}/libhidlbase.so", "/system/lib64/libhidlbase.so"):
            run(["debugfs", "-R", f"dump {path} {runtime}", str(image.with_name("system.img"))], timeout=15)
            if runtime.is_file():
                break
        symbols = dynamic_symbols(runtime) if runtime.is_file() else {}
        return VendorIdentity(fingerprint, int(sdk), digest(library), elf_machine(library), digest(adapter),
                              digest(system_ui), vndk, frozenset(symbols),
                              symbols.get("_ZTVN7android8hardware7IBinderE", 0), digest(framework))
