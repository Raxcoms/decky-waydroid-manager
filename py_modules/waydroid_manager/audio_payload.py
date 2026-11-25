"""Select a compatible launch-scoped ALSA Pulse fix for the installed image."""

import json
from pathlib import Path
import struct
import tempfile

from .display_payload import digest
from .elf_symbols import dynamic_symbols, undefined_symbols
from .image_files import extract, images_directory


MODULE = "libasound_module_pcm_pulse.so"
ABIS = {"armeabi-v7a": ("lib", 1, 40), "arm64-v8a": ("lib64", 2, 183)}


def elf_identity(path: Path) -> tuple[int, int]:
    with path.open("rb") as file:
        header = file.read(20)
    if len(header) != 20 or header[:4] != b"\x7fELF" or header[5] != 1:
        raise RuntimeError("Invalid Android audio library")
    return header[4], struct.unpack_from("<H", header, 18)[0]


def file_identity(path: Path):
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return None
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_mode


def validate_payload(root: Path) -> dict:
    manifest = root / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 1024 * 1024:
        raise RuntimeError("Invalid audio build manifest")
    metadata = json.loads(manifest.read_text())
    if not isinstance(metadata, dict):
        raise RuntimeError("Invalid audio build manifest")
    libraries = metadata.get("libraries")
    if (metadata.get("schemaVersion") != 1 or metadata.get("sdk") != 33
            or not isinstance(libraries, dict) or set(libraries) != set(ABIS)
            or not isinstance(metadata.get("recipeSha256"), str)):
        raise RuntimeError("Invalid audio build manifest")
    for abi, (_, elf_class, machine) in ABIS.items():
        module = root / abi / MODULE
        entry = libraries[abi]
        if not isinstance(entry, dict):
            raise RuntimeError("Invalid audio module manifest")
        if (module.is_symlink() or not module.is_file() or digest(module) != entry.get("sha256")
                or elf_identity(module) != (elf_class, machine)):
            raise RuntimeError("The packaged audio module failed validation")
        imports = undefined_symbols(module)
        alsa = sorted(name for name in imports if name.startswith(("snd_", "_snd_")))
        pulse = sorted(name for name in imports if name.startswith("pa_"))
        if (not alsa or not pulse or alsa != entry.get("alsaSymbols")
                or pulse != entry.get("pulseSymbols")
                or "_snd_pcm_pulse_open" not in dynamic_symbols(module)):
            raise RuntimeError("Invalid audio module ABI requirements")
    return metadata


class AudioPayload:
    def __init__(self, config: Path, plugin: Path):
        self.config = config
        self.root = plugin / "bin/audio-native"
        self.cached_key = None
        self.cached_files = {}

    def files(self, run) -> dict[str, Path]:
        manifest = self.root / "manifest.json"
        if not manifest.is_file():
            return {}
        image = images_directory(self.config) / "vendor.img"
        paths = [self.config / "overlay/vendor/build.prop"]
        for lib, _, _ in ABIS.values():
            paths += [self.config / "overlay/vendor" / lib / name for name in
                      ("hw/" + MODULE, "libasound.so", "libpulse.so")]
        key = (str(image), file_identity(image), file_identity(manifest),
               tuple(file_identity(path) for path in paths),
               tuple(file_identity(self.root / abi / MODULE) for abi in ABIS))
        if key == self.cached_key:
            return dict(self.cached_files)
        files = self._inspect(run)
        self.cached_key, self.cached_files = key, files
        return dict(files)

    def _inspect(self, run) -> dict[str, Path]:
        metadata = validate_payload(self.root)
        files = {}
        with tempfile.TemporaryDirectory(prefix="waydroid-manager-audio-") as directory:
            temp = Path(directory)
            props = extract(self.config, "vendor.img", ("/build.prop",), temp / "build.prop", run)
            values = dict(line.split("=", 1) for line in props.read_text().splitlines() if "=" in line)
            if values.get("ro.vendor.build.version.sdk") != str(metadata["sdk"]):
                return {}
            for abi, (lib, elf_class, machine) in ABIS.items():
                override = self.config / "overlay/vendor" / lib / "hw" / MODULE
                if override.exists() or override.is_symlink():
                    continue
                module = self.root / abi / MODULE
                entry = metadata["libraries"][abi]
                alsa = frozenset(entry["alsaSymbols"])
                pulse = frozenset(entry["pulseSymbols"])
                installed = extract(self.config, "vendor.img", (f"/{lib}/hw/{MODULE}",),
                                    temp / f"{abi}-installed.so", run, missing_ok=True)
                if not installed.is_file() or elf_identity(installed) != (elf_class, machine):
                    continue
                if "_snd_pcm_pulse_open" not in dynamic_symbols(installed):
                    continue
                available = []
                for name in ("libasound.so", "libpulse.so"):
                    source = extract(self.config, "vendor.img", (f"/{lib}/{name}",),
                                     temp / f"{abi}-{name}", run, missing_ok=True)
                    if not source.is_file() or elf_identity(source) != (elf_class, machine):
                        break
                    available.append(dynamic_symbols(source))
                if len(available) == 2 and alsa.issubset(available[0]) and pulse.issubset(available[1]):
                    files[f"vendor/{lib}/hw/{MODULE}"] = module
        return files