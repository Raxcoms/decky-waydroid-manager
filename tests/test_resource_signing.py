from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from waydroid_manager.resource_builder import sign_apk


class ResourceSigningTests(unittest.TestCase):
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
                                'package="waydroid.manager.test"><application android:hasCode="false" /></manifest>')
            aapt = signers[0].with_name("aapt2.exe" if os.name == "nt" else "aapt2")
            unsigned, signed = root / "unsigned.apk", root / "signed.apk"
            subprocess.run([str(aapt), "link", "-I", str(libraries[0]), "--manifest", str(manifest),
                            "--min-sdk-version", "26", "--target-sdk-version", "28", "-o", str(unsigned)], check=True)
            sign_apk(unsigned, signed, root / "identity", Path(shutil.which("openssl")), dict(os.environ))
            subprocess.run([str(signers[0]), "verify", "--min-sdk-version", "26", str(signed)], check=True)

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
