import argparse
import hashlib
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(sdk: Path, java: Path, key: Path, certificate: Path, output: Path, system_ui: Path) -> Path:
    tools = sdk / "build-tools/35.0.0"
    environment = {**os.environ, "JAVA_HOME": str(java)}
    output.mkdir(parents=True, exist_ok=True)

    def tool(name):
        suffix = ".bat" if name == "apksigner" else ".exe"
        return str(tools / (name + suffix if os.name == "nt" else name))

    def run(*args):
        subprocess.run(list(map(str, args)), env=environment, check=True)

    def overlay(directory, name, *link_args):
        source = ROOT / "android/hwc" / directory
        resources = output / f"{directory}-resources.zip"
        run(tool("aapt2"), "compile", "--dir", source / "res", "-o", resources)
        unsigned = output / f"{directory}-unsigned.apk"
        run(tool("aapt2"), "link", "-I", sdk / "platforms/android-28/android.jar",
            "--manifest", source / "AndroidManifest.xml", "--min-sdk-version", "26",
            "--target-sdk-version", "28", "--auto-add-overlay", *link_args,
            "-o", unsigned, resources)
        aligned = output / f"{directory}-aligned.apk"
        run(tool("zipalign"), "-f", "4", unsigned, aligned)
        target = output / name
        run(tool("apksigner"), "sign", "--key", key, "--cert", certificate, "--out", target, aligned)
        run(tool("apksigner"), "verify", target)
        return target

    target = overlay("overlay", "WaydroidManagerExternalDisplay.apk")
    # Keep System UI's 0x7f references separate from the overlay's resource IDs.
    overlay("navigation-overlay", "WaydroidManagerNavigationBar.apk", "-I", system_ui,
            "--package-id", "0x7e", "--allow-reserved-package-id")
    (output / "system-ui.sha256").write_text(hashlib.sha256(system_ui.read_bytes()).hexdigest() + "\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the framework overlay with the Android SDK")
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--system-ui", type=Path, required=True, help="SystemUI.apk from the target Waydroid image")
    parser.add_argument("--output", type=Path, default=ROOT / "out/display-build")
    args = parser.parse_args()
    print(build(args.sdk, args.java, args.key, args.certificate, args.output, args.system_ui))
