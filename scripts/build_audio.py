"""Build Waydroid's ALSA Pulse PCM module for supported ARM Android ABIs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import sys

from native_dependencies import prepare

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "android/audio/sources.json"
sys.path.insert(0, str(ROOT / "py_modules"))
from waydroid_manager.elf_symbols import dynamic_symbols, undefined_symbols


def recipe_digest():
    checksum = hashlib.sha256()
    for name in ("android/audio/sources.json", "android/audio/readiness.patch",
                 "scripts/build_audio.py", "scripts/native_dependencies.py",
                 "py_modules/waydroid_manager/elf_symbols.py",
                 "android/native/profiles/android-13-arm64.json"):
        checksum.update((ROOT / name).read_bytes())
    return checksum.hexdigest()

def run(*command):
    subprocess.run(list(map(str, command)), check=True)

def build(output: Path, cache: Path, ndk: Path):
    output.mkdir(parents=True, exist_ok=True)
    libraries = {}
    with tempfile.TemporaryDirectory(prefix="waydroid-audio-build-") as name:
        work = Path(name)
        source = work / "source"
        prepare(PROFILE, cache, source)
        run("patch", "-d", source / "plugins", "-p1", "--batch", "-i", ROOT / "android/audio/readiness.patch")
        headers = work / "headers/alsa"
        shutil.copytree(source / "alsa/include", headers)
        configuration = (source / "alsa/configure.ac").read_text()
        version = re.search(r"AC_INIT\(alsa-lib,\s*([0-9]+)\.([0-9]+)\.([0-9]+)", configuration)
        if not version:
            raise RuntimeError("Unable to identify the pinned ALSA header version")
        major, minor, sub = map(int, version.groups())
        (headers / "version.h").write_text(
            f"#define SND_LIB_MAJOR {major}\n#define SND_LIB_MINOR {minor}\n"
            f"#define SND_LIB_SUBMINOR {sub}\n#define SND_LIB_EXTRAVER 1000000\n"
            "#define SND_LIB_VER(maj,min,sub) (((maj)<<16)|((min)<<8)|(sub))\n"
            "#define SND_LIB_VERSION SND_LIB_VER(SND_LIB_MAJOR,SND_LIB_MINOR,SND_LIB_SUBMINOR)\n"
            f'#define SND_LIB_VERSION_STR "{major}.{minor}.{sub}"\n')
        includes = re.findall(r"#include <[ae][^>]*\.h>", configuration)
        (headers / "asoundlib.h").write_text(
            (headers / "asoundlib-head.h").read_text() + "\n" + "\n".join(includes) + "\n"
            + (headers / "asoundlib-tail.h").read_text())
        toolchain = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
        for abi, compiler in (("arm64-v8a", "aarch64-linux-android29-clang"),
                              ("armeabi-v7a", "armv7a-linux-androideabi29-clang")):
            target = output / abi
            target.mkdir(parents=True, exist_ok=True)
            stubs = work / ("stubs-" + abi)
            stubs.mkdir()
            empty = work / "empty.c"
            empty.write_text("\n")
            for library in ("asound", "pulse"):
                run(toolchain / compiler, "-shared", "-fPIC", empty,
                    f"-Wl,-soname,lib{library}.so", "-o", stubs / f"lib{library}.so")
            run(toolchain / compiler, "-shared", "-fPIC", "-DPIC", "-D_GNU_SOURCE",
                "-I", work / "headers", "-I", source / "pulse/src",
                source / "plugins/pulse/pcm_pulse.c", source / "plugins/pulse/pulse.c",
                "-L", stubs, "-Wl,--no-as-needed", "-lasound", "-lpulse", "-llog",
                "-Wl,-soname,libasound_module_pcm_pulse.so",
                "-o", target / "libasound_module_pcm_pulse.so")
            module = target / "libasound_module_pcm_pulse.so"
            required = undefined_symbols(module)
            alsa = sorted(name for name in required if name.startswith(("snd_", "_snd_")))
            pulse = sorted(name for name in required if name.startswith("pa_"))
            if not alsa or not pulse or "_snd_pcm_pulse_open" not in dynamic_symbols(module):
                raise RuntimeError("The audio module has an invalid dynamic ABI")
            libraries[abi] = {
                "sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
                "alsaSymbols": alsa,
                "pulseSymbols": pulse,
            }
        shutil.copyfile(source / "plugins/COPYING", output / "NOTICE.txt")
    (output / "manifest.json").write_text(json.dumps({
        "schemaVersion": 1, "sdk": 33, "recipeSha256": recipe_digest(),
        "libraries": libraries,
    }, indent=2) + "\n")
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--ndk", type=Path, default=os.environ.get("ANDROID_NDK_HOME"), required=not os.environ.get("ANDROID_NDK_HOME"))
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache/waydroid-manager-audio")
    args = parser.parse_args()
    print(build(args.output.resolve(), args.cache.resolve(), args.ndk.resolve()))