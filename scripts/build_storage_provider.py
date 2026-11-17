"""Build the owned DocumentsProvider APK; each device signs it with its local key."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def build() -> Path:
    sdk = Path(os.environ.get("ANDROID_HOME") or os.environ["ANDROID_SDK_ROOT"])
    tools = sdk / "build-tools/35.0.0"
    library = sdk / "platforms/android-35/android.jar"
    output = ROOT / "out/storage-provider-build"
    classes, dex = output / "classes", output / "dex"
    classes.mkdir(parents=True, exist_ok=True)
    dex.mkdir(exist_ok=True)
    source = ROOT / "android/storage"
    subprocess.run(["javac", "--release", "11", "--class-path", str(library), "-d", str(classes),
                    *map(str, sorted(source.rglob("*.java")))], check=True)
    subprocess.run([str(tools / "d8"), "--min-api", "26", "--lib", str(library), "--output", str(dex),
                    *map(str, sorted(classes.rglob("*.class")))], check=True)
    target = ROOT / "bin/storage-provider"
    target.mkdir(parents=True, exist_ok=True)
    apk = target / "provider-unsigned.apk"
    # The private offline signer uses v1 signatures, so this helper targets API 28.
    subprocess.run([str(tools / "aapt2"), "link", "-I", str(library), "--manifest", str(source / "AndroidManifest.xml"),
                    "--min-sdk-version", "26", "--target-sdk-version", "28", "-o", str(apk)], check=True)
    with zipfile.ZipFile(apk, "a") as package:
        package.write(dex / "classes.dex", "classes.dex")
    (target / "manifest.json").write_text(json.dumps({"schemaVersion": 1, "file": apk.name,
        "sha256": hashlib.sha256(apk.read_bytes()).hexdigest()}) + "\n")
    return apk


if __name__ == "__main__":
    print(build())
