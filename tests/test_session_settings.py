import configparser
from pathlib import Path, PurePosixPath
import tempfile
import unittest

from waydroid_manager.session_settings import EXTERNAL_PROPERTY, external_mount, external_settings, session_configuration


class SessionSettingsTests(unittest.TestCase):
    def test_existing_external_property_is_not_replaced(self):
        with self.assertRaisesRegex(RuntimeError, "already configured"):
            external_settings(f"[properties]\n{EXTERNAL_PROPERTY}=other\n".encode())

    def test_socket_paths_that_lxc_cannot_parse_are_rejected(self):
        for value in ("/run/external display", "/run/external\nentry", "/run/external\\entry"):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "invalid path"):
                external_mount(PurePosixPath(value))

    def test_properties_are_added_to_their_section_without_changing_other_sections(self):
        for source in (b"[waydroid]\nimages_path=/images", b"[properties]\nfoo=bar",
                       b"[properties]\nfoo=bar\n[other]\nvalue=preserved\n"):
            with self.subTest(source=source):
                result = configparser.ConfigParser()
                result.read_string(external_settings(source).decode())
                self.assertEqual(result["properties"][EXTERNAL_PROPERTY], "wayland-1")
                if b"value=preserved" in source:
                    self.assertEqual(result["other"]["value"], "preserved")

    def test_launch_configuration_is_returned_without_writing_installed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "lxc/waydroid/config"
            config.parent.mkdir(parents=True)
            originals = {config: b"lxc.include = config_session\n",
                         root / "waydroid.cfg": b"[properties]\nfoo=bar\n",
                         root / "waydroid_base.prop": b"ro.hardware.gralloc=gbm\n"}
            for path, content in originals.items():
                path.write_bytes(content)
            result = session_configuration(root, Path("/run/external"))
            self.assertEqual(set(result), set(originals))
            self.assertIn(b"run/xdg/wayland-1 none rbind,create=file", result[config])
            self.assertIn(b"waydroid.external_display_visible=0\n", result[root / "waydroid_base.prop"])
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_single_display_configuration_does_not_read_or_change_other_session_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "waydroid_base.prop"
            base.write_bytes(b"ro.hardware.gralloc=gbm\n")
            self.assertEqual(session_configuration(root, None), {})
            self.assertEqual(list(root.iterdir()), [base])

    def test_existing_external_configuration_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "waydroid_base.prop"
            original = f"  {EXTERNAL_PROPERTY} = other\n".encode()
            base.write_bytes(original)
            with self.assertRaisesRegex(RuntimeError, "already configured"):
                session_configuration(root, Path("/run/external"))
            self.assertEqual(base.read_bytes(), original)

    def test_symlinked_source_configuration_is_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "original.prop"
            outside.write_bytes(b"original")
            try:
                (root / "waydroid_base.prop").symlink_to(outside)
            except OSError:
                self.skipTest("Symlink creation is unavailable")
            with self.assertRaisesRegex(RuntimeError, "not a regular file"):
                session_configuration(root, None)
            self.assertEqual(outside.read_bytes(), b"original")
