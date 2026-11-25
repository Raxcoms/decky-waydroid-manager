import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

from build_native import ROOT, recipe_digest


def check(root: Path) -> None:
    required = ["main.py", "plugin.json", "package.json", "dist/index.js", "README.md", "LICENSE"]
    required += [f"bin/{name}" for name in (
        "waydroid-launcher", "waydroid-game-session", "waydroid-session",
        "waydroid-service", "waydroid-input-sync", "waydroid-wayland-relay", "waydroid-user-files", "waydroid-runtime-env",
    )]
    for name in required:
        path = root / name
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError(f"Missing packaged file: {name}")
        if name.startswith("bin/") and os.name != "nt" and not os.access(path, os.X_OK):
            raise RuntimeError(f"Packaged helper is not executable: {name}")
    if any(root.rglob("*.pyc")) or any(root.rglob("__pycache__")):
        raise RuntimeError("Python caches must not be shipped")
    for path in root.rglob("*"):
        if not path.name.lower().endswith((".apk", ".xapk", ".apk.part", ".xapk.part")):
            continue
        if path == root / "bin/storage-provider/provider-unsigned.apk":
            continue
        raise RuntimeError("Compiled Android packages must be prepared from the installed image, not shipped")
    helper = root / "bin/waydroid-verifier.dex"
    if not helper.is_file() or not helper.read_bytes().startswith(b"dex\n"):
        raise RuntimeError("Build the Android verification helper before packaging")
    if (root / "node_modules").exists() or (root / "tests").exists():
        raise RuntimeError("Development files must not be shipped")
    if "root" not in json.loads((root / "plugin.json").read_text())["flags"]:
        raise RuntimeError("The backend requires Decky's root flag")
    # Import only the staged modules, without running Decky's lifecycle hooks.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "py_modules"))
    sys.modules["decky"] = types.SimpleNamespace(DECKY_PLUGIN_DIR=str(root))
    spec = importlib.util.spec_from_file_location("packaged_backend", root / "main.py")
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    backend.Plugin()
    from waydroid_manager.provider_payload import unsigned_provider
    unsigned_provider(root)
    from waydroid_manager.native_payload import NativePayload
    manifests = list((root / "bin/display-native").glob("*/manifest.json"))
    profiles = {path.stem: path for path in (ROOT / "android/native/profiles").glob("*.json")}
    if not profiles or {path.parent.name for path in manifests} != profiles.keys():
        raise RuntimeError("The packaged native builds do not match the configured profiles")
    for manifest in manifests:
        payload = NativePayload.load(manifest.parent)
        if payload.recipe != recipe_digest(profiles[manifest.parent.name]):
            raise RuntimeError("The packaged display libraries were built from a different native recipe")
        if not payload.binder_vtable_size or not (manifest.parent / "NOTICE.txt").is_file():
            raise RuntimeError("The native ABI contract or license notices are missing")
    from build_audio import recipe_digest as audio_recipe_digest
    from waydroid_manager.audio_payload import validate_payload
    audio = root / "bin/audio-native"
    if (validate_payload(audio).get("recipeSha256") != audio_recipe_digest()
            or not (audio / "NOTICE.txt").is_file()):
        raise RuntimeError("The packaged audio module or license notice is invalid")
    from waydroid_manager.display_payload import digest, elf_machine
    tools = list((root / "bin/display-tools").glob("*/manifest.json"))
    machines = {str(tool["machine"]) for tool in json.loads((ROOT / "android/native/runtime-tools.json").read_text())}
    if not machines or {path.parent.name for path in tools} != machines:
        raise RuntimeError("The packaged runtime tools do not match the configured host architectures")
    for manifest in tools:
        metadata = json.loads(manifest.read_text())
        if str(metadata.get("elfMachine")) != manifest.parent.name or metadata.get("schemaVersion") != 1:
            raise RuntimeError("Invalid private resource tool manifest")
        if not {"aapt2", "openssl", "home-mount", "NOTICE.txt"}.issubset(metadata.get("files", {})):
            raise RuntimeError("The private resource tool bundle is incomplete")
        for name, checksum in metadata["files"].items():
            path = manifest.parent / name
            if Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink() or digest(path) != checksum:
                raise RuntimeError("A packaged runtime tool failed validation")
        for name in ("aapt2", "openssl", "home-mount"):
            if elf_machine(manifest.parent / name) != metadata["elfMachine"]:
                raise RuntimeError("A resource tool has the wrong architecture")
            if not os.access(manifest.parent / name, os.X_OK):
                raise RuntimeError("A private resource tool is not executable")
    for name in ("framework/AndroidManifest.xml", "framework/res/values/config.xml",
                 "navigation/AndroidManifest.xml", "navigation/res/layout/navigation_bar.xml",
                 "navigation/res/layout/recent_apps.xml", "navigation/res/drawable/ic_sysbar_recent.xml",
                 "display_settings.xml", "wayland_tablet.idc"):
        if not (root / "resources/display" / name).is_file():
            raise RuntimeError("The display resource sources are incomplete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate an installable Decky plugin directory on Linux")
    parser.add_argument("plugin", type=Path)
    args = parser.parse_args()
    check(args.plugin.resolve())
    print("Packaged backend imports and runtime files are valid")
