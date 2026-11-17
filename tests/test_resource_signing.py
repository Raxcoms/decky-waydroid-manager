from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from waydroid_manager.resource_builder import sign_apk


class ResourceSigningTests(unittest.TestCase):
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
