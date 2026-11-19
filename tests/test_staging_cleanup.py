from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from waydroid_manager.runtime_display import RuntimeDisplayLease


class StagingCleanupTests(unittest.TestCase):
    def test_recovery_preserves_data_if_staging_contains_a_mount(self):
        for manifest in (None, "[]"):
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "runtime space"
                (root / "view/Home").mkdir(parents=True)
                sentinel = root / "view/Home/sentinel"
                sentinel.write_text("must remain")
                if manifest:
                    (root / "mounts.json").write_text(manifest)
                original = Path.read_text
                target = str(sentinel.parent).replace(" ", "\\040")

                def read(path, *args, **kwargs):
                    if str(path) == "/proc/self/mountinfo":
                        return f"123 1 0:1 / {target} rw - tmpfs tmpfs rw\n"
                    return original(path, *args, **kwargs)

                with patch.object(Path, "read_text", read):
                    with self.assertRaisesRegex(RuntimeError, "still contains a mount"):
                        RuntimeDisplayLease(Path(directory), root).recover()
                self.assertEqual(sentinel.read_text(), "must remain")

    def test_unmounted_staging_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir()
            (root / "owned-file").write_text("temporary")
            RuntimeDisplayLease(Path(directory), root).recover()
            self.assertFalse(root.exists())
