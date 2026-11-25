import argparse
import json
from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parents[1]


def package(output: Path, revision: str | None = None, native: Path | None = None, runtime_tools: Path | None = None) -> Path:
    if revision is not None and not re.fullmatch(r"[0-9a-f]{7,64}", revision):
        raise ValueError("Expected a short Git commit SHA")
    target = output / "waydroid-manager"
    target.mkdir(parents=True, exist_ok=False)
    for name in ("plugin.json", "package.json", "README.md", "LICENSE", "main.py"):
        shutil.copy2(ROOT / name, target / name)
    if revision:
        manifest = target / "package.json"
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        metadata["version"] = f"{metadata['version']}+{revision}"
        manifest.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    for name in ("bin", "dist", "docs", "py_modules"):
        shutil.copytree(ROOT / name, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if native is not None:
        if not any(native.glob("*/manifest.json")):
            raise RuntimeError("The native CI build produced no display artifacts")
        shutil.copytree(native, target / "bin/display-native")
    if runtime_tools is not None:
        shutil.copytree(runtime_tools, target / "bin/display-tools")
        for name in ("aapt2", "openssl", "home-mount"):
            for helper in (target / "bin/display-tools").glob(f"*/{name}"):
                helper.chmod(0o755)
    resources = target / "resources/display"
    resources.mkdir(parents=True)
    for source, name in (("overlay", "framework"), ("navigation-overlay", "navigation")):
        shutil.copytree(ROOT / "android/hwc" / source, resources / name,
                        ignore=shutil.ignore_patterns("Android.bp"))
    for name in ("display_settings.xml", "wayland_tablet.idc"):
        shutil.copyfile(ROOT / "android/hwc" / name, resources / name)
    for script in (target / "bin").iterdir():
        if script.is_file():
            script.chmod(0o755)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage the Decky plugin in an empty output directory")
    parser.add_argument("output", type=Path, nargs="?", default=Path("out"))
    parser.add_argument("--revision", help="Append this Git revision to the packaged Decky version")
    parser.add_argument("--native", type=Path, help="Native libraries produced by the matching CI recipe")
    parser.add_argument("--runtime-tools", type=Path, help="Offline resource compilers packaged by CI")
    args = parser.parse_args()
    print(package(args.output, args.revision, args.native, args.runtime_tools))
