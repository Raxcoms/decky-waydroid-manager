"""Compile and sign resource-only overlays using private host tools."""

import base64
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import zipfile


def _digest(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")


def sign_apk(unsigned: Path, target: Path, signing: Path, openssl: Path, environment: dict) -> None:
    signing.mkdir(mode=0o700, parents=True, exist_ok=True)
    key, certificate = signing / "key.pem", signing / "certificate.pem"
    if not key.exists() and not certificate.exists():
        subprocess.run([str(openssl), "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
                        "-subj", "/CN=Waydroid Manager/", "-days", "36500", "-keyout", str(key),
                        "-out", str(certificate)], env=environment, check=True, capture_output=True, timeout=30)
        key.chmod(0o600)
    if key.is_symlink() or certificate.is_symlink() or not key.is_file() or not certificate.is_file():
        raise RuntimeError("Invalid Android resource signing identity")
    with zipfile.ZipFile(unsigned) as source:
        entries = [(entry, source.read(entry)) for entry in source.infolist() if not entry.filename.startswith("META-INF/")]
    manifest = b"Manifest-Version: 1.0\r\n\r\n"
    for entry, content in entries:
        manifest += f"Name: {entry.filename}\r\nSHA-256-Digest: {_digest(content)}\r\n\r\n".encode()
    signature = f"Signature-Version: 1.0\r\nSHA-256-Digest-Manifest: {_digest(manifest)}\r\n\r\n".encode()
    sf, rsa = target.with_suffix(".sf"), target.with_suffix(".rsa")
    sf.write_bytes(signature)
    subprocess.run([str(openssl), "cms", "-sign", "-binary", "-noattr", "-md", "sha256", "-in", str(sf),
                    "-signer", str(certificate), "-inkey", str(key), "-outform", "DER", "-out", str(rsa)],
                   env=environment, check=True, capture_output=True, timeout=15)
    with zipfile.ZipFile(target, "w") as output:
        for entry, content in entries:
            output.writestr(entry, content)
        output.writestr("META-INF/MANIFEST.MF", manifest)
        output.writestr("META-INF/CERT.SF", signature)
        output.writestr("META-INF/CERT.RSA", rsa.read_bytes())
    sf.unlink()
    rsa.unlink()


def build(resources: Path, tools: Path, framework: Path, system_ui: Path, signing: Path, output: Path) -> None:
    environment = dict(os.environ, LD_LIBRARY_PATH=str(tools / "lib"), OPENSSL_CONF="/dev/null")
    for directory, filename in (("framework", "WaydroidManagerExternalDisplay.apk"),
                                ("navigation", "WaydroidManagerNavigationBar.apk")):
        source = resources / directory
        compiled = output / f"{directory}.zip"
        unsigned = output / f"{directory}-unsigned.apk"
        subprocess.run([str(tools / "aapt2"), "compile", "--dir", str(source / "res"), "-o", str(compiled)],
                       env=environment, check=True, capture_output=True, timeout=30)
        command = [str(tools / "aapt2"), "link", "-I", str(framework), "--manifest", str(source / "AndroidManifest.xml"),
                   "--min-sdk-version", "26", "--target-sdk-version", "28", "--auto-add-overlay"]
        if directory == "navigation":
            command += ["-I", str(system_ui), "--package-id", "0x7e", "--allow-reserved-package-id"]
        subprocess.run([*command, "-o", str(unsigned), str(compiled)], env=environment, check=True,
                       capture_output=True, timeout=30)
        sign_apk(unsigned, output / filename, signing, tools / "openssl", environment)
        unsigned.unlink()
        compiled.unlink()


if __name__ == "__main__":
    try:
        build(*map(Path, sys.argv[1:]))
    except subprocess.CalledProcessError as error:
        sys.stderr.buffer.write(error.stderr or b"Android resource build failed")
        raise SystemExit(1)
