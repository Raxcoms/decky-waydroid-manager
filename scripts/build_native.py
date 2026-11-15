"""Build the native display extension without an Android platform checkout."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

from display_notices import collect
from native_dependencies import file_digest, prepare
from native_headers import generate
from native_symbols import validate


ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def recipe_digest(profile: Path) -> str:
    checksum = hashlib.sha256(profile.read_bytes())
    metadata = json.loads(profile.read_text())
    paths = [*sorted((ROOT / "android/native").rglob("CMakeLists.txt")),
             *sorted((ROOT / "android/native").rglob("*.h")),
             *(ROOT / "scripts" / name for name in
               ("build_native.py", "native_dependencies.py", "native_headers.py", "native_symbols.py", "display_notices.py")),
             *(ROOT / patch["file"] for patch in metadata["patches"])]
    for path in paths:
        checksum.update(path.read_bytes())
    return checksum.hexdigest()


def patched_sources(profile: Path, cache: Path, work: Path) -> tuple[dict, Path]:
    metadata = json.loads(profile.read_text())
    source = work / "source"
    if source.exists():
        return metadata, source
    cached = cache / "sources" / hashlib.sha256(profile.read_bytes()).hexdigest()
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cached.parent) as temporary:
            staging = Path(temporary) / "source"
            prepare(profile, cache / "archives", staging)
            staging.rename(cached)
    with tempfile.TemporaryDirectory(dir=work) as temporary:
        staging = Path(temporary) / "source"
        shutil.copytree(cached, staging, symlinks=True)
        for project in metadata["upstreamPatchProjects"]:
            patches = staging / "vendor/extra/waydroid-patches" / f"base-patches-{metadata['sdk']}" / project
            for patch in sorted(patches.glob("*.patch")):
                run("patch", "-d", staging / project, "-p1", "--batch", "--forward", "-i", patch)
        # Waydroid extends Binder's vtable beyond the standard VNDK snapshot.
        for entry in metadata.get("exportedHeaderPatches", []):
            patches = staging / "vendor/extra/waydroid-patches" / f"base-patches-{metadata['sdk']}" / entry["project"]
            for patch in sorted(patches.glob("*.patch")):
                sections = re.split(r"(?=^diff --git )", patch.read_text(), flags=re.MULTILINE)
                header = entry["include"]
                selected = "".join(section for section in sections
                                   if section.startswith(f"diff --git a/{header} b/{header}\n"))
                if selected:
                    run("patch", "-d", staging / "vndk/include" / entry["project"], "-p1", "--batch", "--forward",
                        input=selected, text=True)
        for patch in metadata["patches"]:
            run("patch", "-d", staging / patch["project"], "-p1", "--batch", "--forward", "-i", ROOT / patch["file"])
        staging.rename(source)
    return metadata, source


def build(profile: Path, cache: Path, directory: Path, output: Path, ndk: Path, jobs: int) -> Path:
    profile = profile.resolve()
    identity = recipe_digest(profile)
    work = directory.resolve() / identity
    work.mkdir(parents=True, exist_ok=True)
    metadata, source = patched_sources(profile, cache.resolve(), work)
    properties = dict(tuple(part.strip() for part in line.split("=", 1))
                      for line in (ndk / "source.properties").read_text().splitlines() if "=" in line)
    if properties.get("Pkg.Revision") != metadata["ndkVersion"]:
        raise RuntimeError(f"This recipe requires Android NDK {metadata['ndkVersion']}")
    host, native = work / "host", work / "native"
    run("cmake", "-S", ROOT / "android/native/host", "-B", host, "-G", "Ninja",
        f"-DNATIVE_DEPS_DIR={source}", "-DCMAKE_BUILD_TYPE=Release")
    run("cmake", "--build", host, "--parallel", jobs)
    generate(source, native / "generated", host / "hidl-gen")
    # Waydroid's extra runtime symbols are checked against the profile after linking.
    run("cmake", "-S", ROOT / "android/native", "-B", native, "-G", "Ninja",
        f"-DCMAKE_TOOLCHAIN_FILE={ndk.resolve() / 'build/cmake/android.toolchain.cmake'}",
        f"-DANDROID_ABI={metadata['abi']}", f"-DANDROID_PLATFORM=android-{metadata['sdk']}", "-DANDROID_STL=none",
        "-DANDROID_ALLOW_UNDEFINED_SYMBOLS=TRUE",
        f"-DNATIVE_DEPS_DIR={source}", f"-DVNDK_ARCH={metadata['vndkArch']}",
        f"-DFFI_ARCH={metadata['ffiArch']}", f"-DFFI_CONFIG={metadata['ffiConfig']}", "-DCMAKE_BUILD_TYPE=Release")
    run("cmake", "--build", native, "--parallel", jobs)
    target = output.resolve() / profile.stem
    target.mkdir(parents=True, exist_ok=True)
    toolchains = list((ndk / "toolchains/llvm/prebuilt").glob("*/bin/llvm-strip"))
    if len(toolchains) != 1:
        raise RuntimeError("Could not identify the NDK strip tool")
    files = {}
    for name in ("hwcomposer.waydroid.so", "libhwc2on1adapter.so"):
        run(toolchains[0], "--strip-unneeded", "-o", target / name, native / name)
        files[name] = file_digest(target / name)
        validate(toolchains[0].with_name("llvm-nm"), target / name, source / "vndk" / metadata["vndkArch"],
                 metadata.get("runtimeSymbols", []), metadata.get("requiredRuntimeSymbols", {}).get(name, []))
    collect(source, target / "NOTICE.txt")
    manifest = {"schemaVersion": 2, "sdk": metadata["sdk"], "vndkVersion": metadata["vndkVersion"],
                "abi": metadata["abi"], "elfMachine": metadata["elfMachine"], "recipeSha256": identity,
                "files": files, "dependencies": metadata["dependencies"],
                "capabilities": metadata.get("capabilities", []), "runtimeSymbols": metadata.get("runtimeSymbols", [])}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache/waydroid-manager-native")
    parser.add_argument("--build", type=Path, default=ROOT / "out/native-build")
    parser.add_argument("--ndk", type=Path, default=os.environ.get("ANDROID_NDK_HOME"), required=not os.environ.get("ANDROID_NDK_HOME"))
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    print(build(args.profile, args.cache, args.build, args.output, args.ndk, args.jobs))
