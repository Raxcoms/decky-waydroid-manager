import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import types


def check(root: Path) -> None:
    required = ["main.py", "plugin.json", "package.json", "dist/index.js", "README.md", "LICENSE"]
    required += [f"bin/{name}" for name in (
        "waydroid-launcher", "waydroid-game-session", "waydroid-session",
        "waydroid-service", "waydroid-input-sync", "waydroid-wayland-relay", "waydroid-user-files",
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
        if (path.name != "WaydroidManagerExternalDisplay.apk"
                or not path.is_relative_to(root / "bin/display-payloads")):
            raise RuntimeError("Android test packages must not be shipped")
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate an installable Decky plugin directory on Linux")
    parser.add_argument("plugin", type=Path)
    args = parser.parse_args()
    check(args.plugin.resolve())
    print("Packaged backend imports and runtime files are valid")
