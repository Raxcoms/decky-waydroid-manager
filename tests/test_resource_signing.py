from pathlib import Path
import io
import os
import shutil
import subprocess
import struct
import tempfile
import unittest
import zipfile

from waydroid_manager.resource_builder import sign_apk, write_entry


class ResourceSigningTests(unittest.TestCase):
    def test_resource_table_is_stored_and_aligned_after_archive_rewriting(self):
        for size in range(8):
            with self.subTest(size=size):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w") as output:
                    output.writestr("AndroidManifest.xml", bytes(size))
                    entry = zipfile.ZipInfo("resources.arsc")
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.extra = struct.pack("<HH", 0xcafe, 1) + b"x"
                    write_entry(output, entry, b"resource table")
                with zipfile.ZipFile(stream) as archive:
                    table = archive.getinfo("resources.arsc")
                    stream.seek(table.header_offset)
                    header = struct.unpack("<IHHHHHIIIHH", stream.read(30))
                    offset = table.header_offset + 30 + header[-2] + header[-1]
                    self.assertEqual(offset % 4, 0)
                    self.assertEqual(table.compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(archive.read(table), b"resource table")
                    self.assertEqual(entry.compress_type, zipfile.ZIP_DEFLATED)
                    if len(table.extra) > len(entry.extra):
                        tag, length, alignment = struct.unpack("<HHH", table.extra[len(entry.extra):][:6])
                        self.assertEqual((tag, alignment), (0xd935, 4))
                        self.assertEqual(length + 4, len(table.extra) - len(entry.extra))

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is needed")
    def test_incomplete_first_signing_identity_is_recovered_as_a_complete_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signing = root / "identity"
            signing.mkdir()
            (signing / "key.pem").write_text("interrupted")
            unsigned = root / "unsigned.apk"
            with zipfile.ZipFile(unsigned, "w") as archive:
                archive.writestr("AndroidManifest.xml", b"manifest")
            sign_apk(unsigned, root / "signed.apk", signing, Path(shutil.which("openssl")), dict(os.environ))
            self.assertTrue((signing / "certificate.pem").is_file())
            self.assertNotEqual((signing / "key.pem").read_text(), "interrupted")
    def test_android_verifier_accepts_the_signed_resource_package(self):
        sdk = Path(os.environ.get("ANDROID_HOME", "/nonexistent-sdk"))
        suffix = ".bat" if os.name == "nt" else ""
        signers = sorted((sdk / "build-tools").glob("*/apksigner" + suffix), reverse=True)
        libraries = sorted((sdk / "platforms").glob("*/android.jar"), reverse=True)
        if not signers or not libraries or not shutil.which("openssl"):
            self.skipTest("The Android SDK and OpenSSL are needed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "AndroidManifest.xml"
            manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
                                'package="waydroid.manager.test"><application android:hasCode="false" '
                                'android:label="@string/app_name" /></manifest>')
            aapt = signers[0].with_name("aapt2.exe" if os.name == "nt" else "aapt2")
            resources = root / "res/values"
            resources.mkdir(parents=True)
            (resources / "strings.xml").write_text('<resources><string name="app_name">Test</string></resources>')
            compiled = root / "resources.zip"
            subprocess.run([str(aapt), "compile", "--dir", str(root / "res"), "-o", str(compiled)], check=True)
            unsigned, signed = root / "unsigned.apk", root / "signed.apk"
            subprocess.run([str(aapt), "link", "-I", str(libraries[0]), "--manifest", str(manifest),
                            "--min-sdk-version", "26", "--target-sdk-version", "28", "-o", str(unsigned),
                            str(compiled)], check=True)
            sign_apk(unsigned, signed, root / "identity", Path(shutil.which("openssl")), dict(os.environ))
            subprocess.run([str(signers[0]), "verify", "--min-sdk-version", "26", str(signed)], check=True)
            with zipfile.ZipFile(signed) as archive, signed.open("rb") as stream:
                table = archive.getinfo("resources.arsc")
                stream.seek(table.header_offset)
                header = struct.unpack("<IHHHHHIIIHH", stream.read(30))
                self.assertEqual((table.header_offset + 30 + header[-2] + header[-1]) % 4, 0)
                self.assertEqual(table.compress_type, zipfile.ZIP_STORED)

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is needed")
    def test_signature_verifies_and_uses_a_stable_private_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unsigned, signed = root / "unsigned.apk", root / "signed.apk"
            with zipfile.ZipFile(unsigned, "w") as archive:
                archive.writestr("AndroidManifest.xml", b"manifest")
                archive.writestr("resources.arsc", b"resources")
            signing = root / "identity"
            openssl = Path(shutil.which("openssl"))
            sign_apk(unsigned, signed, signing, openssl, dict(os.environ))
            original = (signing / "certificate.pem").read_bytes()
            with zipfile.ZipFile(signed) as archive:
                signature = archive.read("META-INF/CERT.SF")
                (root / "signature.sf").write_bytes(signature)
                (root / "signature.rsa").write_bytes(archive.read("META-INF/CERT.RSA"))
                self.assertEqual(archive.read("resources.arsc"), b"resources")
            verified = subprocess.check_output([str(openssl), "cms", "-verify", "-binary", "-inform", "DER",
                "-in", str(root / "signature.rsa"), "-content", str(root / "signature.sf"), "-noverify"], stderr=subprocess.PIPE)
            self.assertEqual(verified, signature)
            sign_apk(unsigned, signed, signing, openssl, dict(os.environ))
            self.assertEqual((signing / "certificate.pem").read_bytes(), original)
