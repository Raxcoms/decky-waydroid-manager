import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from waydroid_manager.legacy_overlay import LegacyOverlayRecovery


class LegacyOverlayRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.recovery = LegacyOverlayRecovery(self.root / "waydroid")
        self.relative = Path("vendor/lib64/hw/hwcomposer.waydroid.so")
        self.target = self.recovery.overlay / self.relative

    def stage(self, original=None, *, phase="active", backup=True):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"payload")
        self.recovery.root.mkdir(parents=True)
        entry = {"path": self.relative.as_posix(), "created": original is None, "mode": 0o644,
                 "sourceDigest": hashlib.sha256(b"payload").hexdigest()}
        if original is not None and backup:
            saved = self.recovery.backups / self.relative
            saved.parent.mkdir(parents=True)
            saved.write_bytes(original)
            saved.chmod(0o640)
        state = {"version": 1, "phase": phase, "entries": [entry]}
        self.recovery.manifest.write_text(json.dumps(state))

    def test_no_previous_manifest_needs_no_recovery(self):
        self.assertFalse(self.recovery.recover())

    def test_removes_only_an_unchanged_created_file(self):
        self.stage()
        self.assertTrue(self.recovery.recover())
        self.assertFalse(self.target.exists())
        self.assertFalse(self.recovery.root.exists())

    def test_restores_an_existing_overlay_file_and_its_permissions(self):
        self.stage(b"existing")
        self.assertTrue(self.recovery.recover())
        self.assertEqual(self.target.read_bytes(), b"existing")
        if os.name != "nt":
            self.assertEqual(self.target.stat().st_mode & 0o777, 0o640)

    def test_handles_an_interrupted_stage(self):
        self.stage(b"existing", phase="staging")
        self.assertTrue(self.recovery.recover())
        self.assertEqual(self.target.read_bytes(), b"existing")

    def test_preserves_another_owners_change(self):
        self.stage()
        self.target.write_bytes(b"other")
        with self.assertRaisesRegex(RuntimeError, "target changed"):
            self.recovery.recover()
        self.assertEqual(self.target.read_bytes(), b"other")
        self.assertTrue(self.recovery.manifest.exists())

    def test_missing_backup_preserves_the_file_and_recovery_record(self):
        self.stage(b"existing", backup=False)
        with self.assertRaisesRegex(RuntimeError, "backup is missing"):
            self.recovery.recover()
        self.assertEqual(self.target.read_bytes(), b"payload")
        self.assertTrue(self.recovery.manifest.exists())

    def test_retry_accepts_files_already_restored_before_another_entry_failed(self):
        self.stage(b"existing")
        relative = Path("vendor/lib64/other.so")
        other = self.recovery.overlay / relative
        other.write_bytes(b"second payload")
        backup = self.recovery.backups / relative
        backup.write_bytes(b"second original")
        state = json.loads(self.recovery.manifest.read_text())
        state["entries"].append({"path": relative.as_posix(), "created": False, "mode": 0o644,
                                 "sourceDigest": hashlib.sha256(b"second payload").hexdigest()})
        self.recovery.manifest.write_text(json.dumps(state))
        self.target.write_bytes(b"another change")
        with self.assertRaisesRegex(RuntimeError, "target changed"):
            self.recovery.recover()
        self.assertEqual(other.read_bytes(), b"second original")
        self.target.write_bytes(b"payload")
        self.assertTrue(self.recovery.recover())
        self.assertEqual(self.target.read_bytes(), b"existing")
        self.assertEqual(other.read_bytes(), b"second original")
        self.assertFalse(self.recovery.root.exists())

    def test_manifest_paths_cannot_escape_the_overlay(self):
        self.stage()
        outside = self.root / "outside"
        outside.write_bytes(b"preserved")
        state = json.loads(self.recovery.manifest.read_text())
        state["entries"][0]["path"] = "../../outside"
        self.recovery.manifest.write_text(json.dumps(state))
        with self.assertRaisesRegex(RuntimeError, "Invalid Waydroid overlay path"):
            self.recovery.recover()
        self.assertEqual(outside.read_bytes(), b"preserved")
