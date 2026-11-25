"""Build Waydroid's ALSA Pulse PCM module for supported ARM Android ABIs."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from native_dependencies import prepare

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "android/audio/sources.json"

def run(*command):
    subprocess.run(list(map(str, command)), check=True)

def build(output: Path, cache: Path, ndk: Path):
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
            target.mkdir(parents=True)
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
                "-L", stubs, "-Wl,--no-as-needed", "-lasound", "-lpulse",
                "-Wl,-soname,libasound_module_pcm_pulse.so",
                "-o", target / "libasound_module_pcm_pulse.so")
            run(toolchain / "llvm-readelf", "-d", target / "libasound_module_pcm_pulse.so")
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--ndk", type=Path, default=os.environ.get("ANDROID_NDK_HOME"), required=not os.environ.get("ANDROID_NDK_HOME"))
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache/waydroid-manager-audio")
    args = parser.parse_args()
    print(build(args.output.resolve(), args.cache.resolve(), args.ndk.resolve()))