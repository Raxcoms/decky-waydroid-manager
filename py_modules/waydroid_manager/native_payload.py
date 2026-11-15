"""Validate CI-built native components separately from image-specific resources."""

from dataclasses import dataclass
import json
from pathlib import Path

from .display_payload import digest, elf_machine


NATIVE_FILES = ("hwcomposer.waydroid.so", "libhwc2on1adapter.so")


@dataclass(frozen=True)
class NativePayload:
    root: Path
    sdk: int
    vndk: str
    machine: int
    recipe: str
    capabilities: frozenset[str] = frozenset()

    @classmethod
    def load(cls, root: Path) -> "NativePayload":
        manifest = root / "manifest.json"
        if manifest.is_symlink() or manifest.stat().st_size > 1024 * 1024:
            raise RuntimeError("Invalid native display manifest")
        metadata = json.loads(manifest.read_text())
        if (metadata.get("schemaVersion") != 2 or type(metadata.get("sdk")) is not int
                or type(metadata.get("elfMachine")) is not int or not isinstance(metadata.get("vndkVersion"), str)
                or set(metadata.get("files", {})) != set(NATIVE_FILES)):
            raise RuntimeError("Invalid native display manifest")
        for name, expected in metadata["files"].items():
            source = root / name
            if (source.is_symlink() or not source.is_file() or digest(source) != expected
                    or elf_machine(source) != metadata["elfMachine"]):
                raise RuntimeError("Native display component failed validation")
        capabilities = metadata.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(isinstance(value, str) for value in capabilities):
            raise RuntimeError("Invalid native display capabilities")
        return cls(root, metadata["sdk"], metadata["vndkVersion"], metadata["elfMachine"], metadata["recipeSha256"],
                   frozenset(capabilities))


def select_native(directory: Path, sdk: int, vndk: str, machine: int) -> NativePayload:
    matches = []
    for manifest in sorted(directory.glob("*/manifest.json")):
        payload = NativePayload.load(manifest.parent)
        if (payload.sdk, payload.vndk, payload.machine) == (sdk, vndk, machine):
            matches.append(payload)
    if len(matches) != 1:
        raise RuntimeError("No unique compatible native display build is available for this Android ABI")
    return matches[0]
