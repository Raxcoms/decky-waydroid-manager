import argparse
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(sdk: Path, java: Path) -> Path:
    environment = {**os.environ, "JAVA_HOME": str(java)}
    tools = sdk / "build-tools/35.0.0"
    library = sdk / "platforms/android-35/android.jar"
    output = ROOT / "out/display-probe"
    classes, dex = output / "classes", output / "dex"
    classes.mkdir(parents=True, exist_ok=True)
    dex.mkdir(exist_ok=True)
    source = ROOT / "tests/android/display_probe"

    def tool(directory: Path, name: str) -> str:
        suffix = ".bat" if name in {"d8", "apksigner"} else ".exe"
        return str(directory / (name + suffix if os.name == "nt" else name))

    def run(*args):
        subprocess.run(list(map(str, args)), env=environment, check=True)

    run(tool(java / "bin", "javac"), "--release", "11", "-classpath", library,
        "-d", classes, source / "ProbeActivity.java")
    run(tool(tools, "d8"), "--min-api", "26", "--lib", library, "--output", dex,
        *sorted(classes.rglob("*.class")))
    unsigned = output / "unsigned.apk"
    run(tool(tools, "aapt2"), "link", "-I", library, "--manifest", source / "AndroidManifest.xml",
        "--min-sdk-version", "26", "--target-sdk-version", "28", "-o", unsigned)
    with zipfile.ZipFile(unsigned, "a") as archive:
        archive.write(dex / "classes.dex", "classes.dex")
    keystore = output / "debug.keystore"
    if not keystore.exists():
        run(tool(java / "bin", "keytool"), "-genkeypair", "-keystore", keystore,
            "-storepass", "android", "-keypass", "android", "-alias", "androiddebugkey",
            "-dname", "CN=Android Debug,O=Android,C=US", "-keyalg", "RSA", "-validity", "30")
    aligned = output / "aligned.apk"
    run(tool(tools, "zipalign"), "-f", "4", unsigned, aligned)
    target = output / "display-probe.apk"
    subprocess.run([tool(tools, "apksigner"), "sign", "--ks", str(keystore),
                    "--ks-pass", "pass:android", "--out", str(target), str(aligned)],
                   env=environment, check=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the temporary external-display smoke test")
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.sdk, args.java))
