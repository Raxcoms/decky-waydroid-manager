"""Compile and sign resource-only overlays using private host tools."""

import base64
import copy
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile


def _digest(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")


def write_entry(output: zipfile.ZipFile, entry: zipfile.ZipInfo, content: bytes) -> None:
    entry = copy.copy(entry)
    if entry.filename == "resources.arsc":
        # An unaligned overlay table also makes Android reject otherwise valid apps.
        entry.compress_type = zipfile.ZIP_STORED
        offset = output.fp.tell() + 30 + len(entry.filename.encode("utf-8")) + len(entry.extra)
        if offset % 4:
            padding = (-offset - 6) % 4
            entry.extra += struct.pack("<HHH", 0xd935, 2 + padding, 4) + bytes(padding)
    output.writestr(entry, content)


def sign_apk(unsigned: Path, target: Path, signing: Path, openssl: Path, environment: dict) -> None:
    key, certificate = signing / "key.pem", signing / "certificate.pem"
    if signing.is_symlink():
        raise RuntimeError("Invalid Android resource signing identity")
    if not key.exists() or not certificate.exists():
        signing.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="signing-", dir=signing.parent) as directory:
            staged = Path(directory) / "identity"
            staged.mkdir(mode=0o700)
            subprocess.run([str(openssl), "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
                            "-subj", "/CN=Waydroid Manager/", "-days", "36500", "-keyout", str(staged / "key.pem"),
                            "-out", str(staged / "certificate.pem")], env=environment, check=True, capture_output=True, timeout=30)
            (staged / "key.pem").chmod(0o600)
            for path in staged.iterdir():
                with path.open("rb") as file:
                    os.fsync(file.fileno())
            if signing.exists():
                if not signing.is_dir() or any(path.name not in {"key.pem", "certificate.pem"} for path in signing.iterdir()):
                    raise RuntimeError("Invalid Android resource signing identity")
                shutil.rmtree(signing)
            staged.rename(signing)
    if key.is_symlink() or certificate.is_symlink() or not key.is_file() or not certificate.is_file():
        raise RuntimeError("Invalid Android resource signing identity")
    with zipfile.ZipFile(unsigned) as source:
        entries = [(entry, source.read(entry)) for entry in source.infolist() if not entry.filename.startswith("META-INF/")]
    sections = []
    for entry, content in entries:
        section = f"Name: {entry.filename}\r\nSHA-256-Digest: {_digest(content)}\r\n\r\n".encode()
        sections.append((entry.filename, section))
    manifest = b"Manifest-Version: 1.0\r\n\r\n" + b"".join(section for _, section in sections)
    signature = f"Signature-Version: 1.0\r\nSHA-256-Digest-Manifest: {_digest(manifest)}\r\n\r\n".encode()
    for name, section in sections:
        signature += f"Name: {name}\r\nSHA-256-Digest: {_digest(section)}\r\n\r\n".encode()
    sf, rsa = target.with_suffix(".sf"), target.with_suffix(".rsa")
    sf.write_bytes(signature)
    subprocess.run([str(openssl), "cms", "-sign", "-binary", "-noattr", "-md", "sha256", "-in", str(sf),
                    "-signer", str(certificate), "-inkey", str(key), "-outform", "DER", "-out", str(rsa)],
                   env=environment, check=True, capture_output=True, timeout=15)
    with zipfile.ZipFile(target, "w") as output:
        for entry, content in entries:
            write_entry(output, entry, content)
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
        if sys.argv[1:2] == ["--sign"]:
            unsigned, target, signing, tools = map(Path, sys.argv[2:])
            environment = dict(os.environ, LD_LIBRARY_PATH=str(tools / "lib"), OPENSSL_CONF="/dev/null")
            sign_apk(unsigned, target, signing, tools / "openssl", environment)
        else:
            build(*map(Path, sys.argv[1:]))
    except subprocess.CalledProcessError as error:
        sys.stderr.buffer.write(error.stderr or b"Android resource build failed")
        raise SystemExit(1)
