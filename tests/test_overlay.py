from pathlib import Path
import sys
import os
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.overlay import OverlayLease


class OverlayLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "payload.so"
        self.source.write_bytes(b"payload")
        self.lease = OverlayLease(self.root / "waydroid")
        self.relative = Path("vendor/lib64/hw/hwcomposer.waydroid.so")

    def test_acquire_and_recover_remove_a_new_file(self):
        self.lease.acquire({self.relative: self.source})
        target = self.lease.overlay / self.relative
        self.assertEqual(target.read_bytes(), b"payload")
        self.assertTrue(self.lease.recover())
        self.assertFalse(target.exists())
        self.assertFalse(self.lease.manifest.exists())

    def test_recover_restores_an_existing_overlay_file(self):
        target = self.lease.overlay / self.relative
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing")
        target.chmod(0o640)
        self.lease.acquire({self.relative: self.source})
        self.assertEqual(target.read_bytes(), b"payload")
        self.lease.recover()
        self.assertEqual(target.read_bytes(), b"existing")
        if os.name != "nt":
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_invalid_paths_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid"):
            self.lease.acquire({"../vendor/lib.so": self.source})

    def test_recovery_handles_an_interrupted_stage(self):
        target = self.lease.overlay / self.relative
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing")
        entry = self.lease._entry(self.relative, self.source)
        self.lease._write_manifest({"version": 1, "phase": "staging", "entries": [entry]})
        self.lease._copy(target, self.lease.backups / self.relative, 0o644)
        self.lease._copy(self.source, target, 0o644)
        self.lease.recover()
        self.assertEqual(target.read_bytes(), b"existing")
