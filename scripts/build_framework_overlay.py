import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(sdk: Path, java: Path, key: Path, certificate: Path, output: Path) -> Path:
    tools = sdk / "build-tools/35.0.0"
    environment = {**os.environ, "JAVA_HOME": str(java)}
    source = ROOT / "android/hwc/overlay"
    output.mkdir(parents=True, exist_ok=True)

    def tool(name):
        suffix = ".bat" if name == "apksigner" else ".exe"
        return str(tools / (name + suffix if os.name == "nt" else name))

    def run(*args):
        subprocess.run(list(map(str, args)), env=environment, check=True)

    resources = output / "overlay-resources.zip"
    run(tool("aapt2"), "compile", "--dir", source / "res", "-o", resources)
    unsigned = output / "overlay-unsigned.apk"
    run(tool("aapt2"), "link", "-I", sdk / "platforms/android-28/android.jar",
        "--manifest", source / "AndroidManifest.xml", "--min-sdk-version", "26",
        "--target-sdk-version", "28", "--auto-add-overlay", "-o", unsigned, resources)
    aligned = output / "overlay-aligned.apk"
    run(tool("zipalign"), "-f", "4", unsigned, aligned)
    target = output / "WaydroidManagerExternalDisplay.apk"
    run(tool("apksigner"), "sign", "--key", key, "--cert", certificate, "--out", target, aligned)
    run(tool("apksigner"), "verify", target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the framework overlay with the Android SDK")
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "out/display-build")
    args = parser.parse_args()
    print(build(args.sdk, args.java, args.key, args.certificate, args.output))
