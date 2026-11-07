import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def build() -> Path:
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        raise RuntimeError("Set ANDROID_HOME to the Android SDK directory")
    sdk = Path(sdk)
    tools = sdk / "build-tools/35.0.0"
    d8 = tools / ("d8.bat" if os.name == "nt" else "d8")
    library = sdk / "platforms/android-35/android.jar"
    java = Path(os.environ["JAVA_HOME"]) / "bin" if os.environ.get("JAVA_HOME") else None
    javac = str(java / ("javac.exe" if os.name == "nt" else "javac")) if java else "javac"
    output = ROOT / "out/android-build"
    dex = output / "dex"
    dex.mkdir(parents=True, exist_ok=True)
    sources = sorted((ROOT / "android").glob("*.java"))
    subprocess.run([javac, "--release", "11", "-d", str(output), *map(str, sources)], check=True)
    subprocess.run([str(d8), "--min-api", "26", "--lib", str(library), "--output", str(dex),
                    *(str(output / "waydroid/manager" / (source.stem + ".class")) for source in sources)], check=True)
    target = ROOT / "bin/waydroid-verifier.dex"
    shutil.copyfile(dex / "classes.dex", target)
    return target


if __name__ == "__main__":
    print(build())
