from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.image import run_init


class ImageProgressTests(unittest.TestCase):
    def test_progress_uses_waydroid_download_measurements_and_verification_stage(self):
        progress = []
        script = (
            "print('[12:00:00] Downloading system');"
            "print('\\r[Downloading] 22.5 MB/ 90 MB', end='');"
            "print('\\r[Downloading] 90 MB/90 MB');"
            "print('[12:00:05] Validating system image');"
            "print('[12:00:06] Downloading vendor');"
            "print('\\r[Downloading] 5 MB/10 MB');"
        )
        run_init([sys.executable, "-c", script], lambda *state: progress.append(state), timeout=10)
        self.assertEqual(progress, [
            ("downloading", None), ("downloading", 25), ("downloading", 100),
            ("finalizing", None), ("downloading", None), ("downloading", 50),
        ])

    def test_failed_initialization_keeps_cli_error(self):
        with self.assertRaisesRegex(RuntimeError, "No images found on system channel"):
            run_init([
                sys.executable, "-c", "print('No images found on system channel'); raise SystemExit(1)",
            ], lambda *_: None, timeout=10)
