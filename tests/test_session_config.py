from pathlib import Path
import json
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.session_config import FRAGMENT, PROPERTY, SessionConfigLease


class SessionConfigLeaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        lxc = self.root / "lxc/waydroid"
        lxc.mkdir(parents=True)
        self.config = lxc / "config"
        self.config.write_text("lxc.include = config_session\n", encoding="utf-8")
        self.settings = self.root / "waydroid.cfg"
        self.settings.write_text("[waydroid]\n\n[properties]\nfoo=bar\n", encoding="utf-8")
        (self.root / "waydroid_base.prop").write_bytes(b"ro.hardware.gralloc=gbm\n")
        self.socket = Path("/run/user/1000/external-wayland")
        self.lease = SessionConfigLease(self.root)

    def tearDown(self):
        self.directory.cleanup()

    def test_acquire_and_recover_restore_existing_files(self):
        original_config = self.config.read_bytes()
        original_settings = self.settings.read_bytes()
        self.lease.acquire(self.socket)
        self.assertIn(FRAGMENT, self.config.read_text(encoding="utf-8"))
        self.assertIn(PROPERTY, self.settings.read_text(encoding="utf-8"))
        self.assertEqual(
            (self.root / "lxc/waydroid" / FRAGMENT).read_text(encoding="utf-8"),
            "lxc.mount.entry = /run/user/1000/external-wayland run/xdg/wayland-1 none rbind,create=file 0 0\n",
        )
        self.assertTrue(self.lease.recover())
        self.assertEqual(self.config.read_bytes(), original_config)
        self.assertEqual(self.settings.read_bytes(), original_settings)
        self.assertFalse((self.root / "lxc/waydroid" / FRAGMENT).exists())
        self.assertEqual((self.root / "waydroid_base.prop").read_bytes(), b"ro.hardware.gralloc=gbm\n")

    def test_recovery_does_not_overwrite_another_change(self):
        self.lease.acquire(self.socket)
        self.settings.write_text("[properties]\nother=value\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.lease.recover()

    def test_existing_external_property_is_not_replaced(self):
        self.settings.write_text(f"[properties]\n{PROPERTY}=other\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "already configured"):
            self.lease.acquire(self.socket)

    def test_rejects_socket_paths_that_lxc_cannot_parse(self):
        with self.assertRaisesRegex(RuntimeError, "invalid path"):
            self.lease.acquire(Path("/run/user/1000/external display"))

    def test_retry_after_partial_recovery_preserves_originals(self):
        original = self.settings.read_bytes()
        self.lease.acquire(self.socket)
        staged = self.settings.read_bytes()
        self.settings.write_bytes(b"other change")
        with self.assertRaises(RuntimeError):
            self.lease.recover()
        self.settings.write_bytes(staged)
        self.assertTrue(self.lease.recover())
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertFalse(self.lease.root.exists())

    def test_manifest_cannot_restore_a_path_outside_the_transaction(self):
        self.lease.acquire(self.socket)
        state = json.loads(self.lease.manifest.read_text())
        state["entries"][0]["path"] = "../outside"
        self.lease.manifest.write_text(json.dumps(state))
        with self.assertRaisesRegex(RuntimeError, "manifest is invalid"):
            self.lease.recover()

    def test_properties_without_final_newline_are_separated(self):
        self.settings.write_bytes(b"[properties]\nfoo=bar")
        self.lease.acquire(self.socket)
        self.assertIn(b"foo=bar\nwaydroid.wayland_display_ext=wayland-1\n", self.settings.read_bytes())
