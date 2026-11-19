import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from waydroid_manager.legacy_session import FRAGMENT, LegacySessionRecovery


class LegacySessionRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.recovery = LegacySessionRecovery(self.root)
        self.originals = {
            "config": (Path("lxc/waydroid/config"), b"lxc.include = config_session\n"),
            "settings": (Path("waydroid.cfg"), b"[properties]\nfoo=bar\n"),
            "fragment": (Path("lxc/waydroid") / FRAGMENT, None),
            "baseProperties": (Path("waydroid_base.prop"), b"ro.hardware.gralloc=gbm\n"),
        }
        self.staged = {
            "config": b"lxc.include = config_session\n# Waydroid Manager second screen\nlxc.include = fragment\n",
            "settings": b"[properties]\nfoo=bar\nwaydroid.wayland_display_ext=wayland-1\n",
            "fragment": b"lxc.mount.entry = /run/external run/xdg/wayland-1 none rbind,create=file 0 0\n",
            "baseProperties": b"ro.hardware.gralloc=gbm\nwaydroid.wayland_display_ext=wayland-1\n",
        }

    def stage(self, *, applied=None):
        entries = []
        for name, (relative, original) in self.originals.items():
            installed = self.root / relative
            installed.parent.mkdir(parents=True, exist_ok=True)
            changed = applied is None or name in applied
            if original is not None:
                installed.write_bytes(original)
                if changed:
                    backup = self.recovery.backups / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    backup.write_bytes(original)
            if changed:
                installed.write_bytes(self.staged[name])
            entries.append({"name": name, "path": str(relative), "created": original is None,
                            "mode": 0o644, "sourceDigest": hashlib.sha256(self.staged[name]).hexdigest(),
                            "originalDigest": hashlib.sha256(original).hexdigest() if original is not None else None})
        self.recovery.root.mkdir(parents=True, exist_ok=True)
        self.recovery.manifest.write_text(json.dumps({"version": 1,
            "phase": "active" if applied is None else "staging", "entries": entries}))

    def assert_originals(self):
        for relative, original in self.originals.values():
            path = self.root / relative
            if original is None:
                self.assertFalse(path.exists())
            else:
                self.assertEqual(path.read_bytes(), original)

    def test_no_previous_manifest_needs_no_recovery(self):
        self.assertFalse(self.recovery.recover())

    def test_restores_configuration_and_removes_the_old_fragment(self):
        self.stage()
        self.assertTrue(self.recovery.recover())
        self.assert_originals()
        self.assertFalse(self.recovery.root.exists())

    def test_interrupted_staging_does_not_need_backups_for_untouched_files(self):
        self.stage(applied={"config"})
        self.assertTrue(self.recovery.recover())
        self.assert_originals()

    def test_retry_after_partial_recovery_preserves_originals(self):
        self.stage()
        settings = self.root / "waydroid.cfg"
        settings.write_bytes(b"another change")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.recovery.recover()
        self.assertEqual(settings.read_bytes(), b"another change")
        settings.write_bytes(self.staged["settings"])
        self.assertTrue(self.recovery.recover())
        self.assert_originals()

    def test_modified_backup_is_not_restored(self):
        self.stage()
        (self.recovery.backups / "waydroid.cfg").write_bytes(b"modified")
        with self.assertRaisesRegex(RuntimeError, "backup changed"):
            self.recovery.recover()
        self.assertEqual((self.root / "waydroid.cfg").read_bytes(), self.staged["settings"])
        self.assertTrue(self.recovery.manifest.exists())

    def test_manifest_cannot_restore_a_path_outside_the_transaction(self):
        self.stage()
        state = json.loads(self.recovery.manifest.read_text())
        state["entries"][0]["path"] = "../outside"
        self.recovery.manifest.write_text(json.dumps(state))
        with self.assertRaisesRegex(RuntimeError, "manifest is invalid"):
            self.recovery.recover()
        for name, (relative, _) in self.originals.items():
            self.assertEqual((self.root / relative).read_bytes(), self.staged[name])
