import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.second_screen import (
    DISPLAY_VARIABLE,
    ENVIRONMENT_VARIABLE,
    discover_external_display,
)


@unittest.skipUnless(hasattr(socket, "AF_UNIX") and hasattr(os, "getuid"), "Requires Unix sockets")
class ExternalDisplayTests(unittest.TestCase):
    def test_uses_an_explicit_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            path = runtime / "external"
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(path))
                display = discover_external_display(
                    os.getuid(), {DISPLAY_VARIABLE: "external"}, runtime,
                )
            self.assertEqual(display.socket, path)

    def test_reads_a_host_environment_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            path = runtime / "external"
            environment = runtime / "host-output-env"
            environment.write_text("WAYLAND_DISPLAY=external\n", encoding="utf-8")
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(path))
                display = discover_external_display(os.getuid(), {}, runtime)
            self.assertEqual(display.socket, path)

    def test_explicit_environment_file_accepts_shell_quoting(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            path = runtime / "external"
            environment = runtime / "provided-env"
            environment.write_text("WAYLAND_DISPLAY='external'\n", encoding="utf-8")
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(path))
                display = discover_external_display(
                    os.getuid(), {ENVIRONMENT_VARIABLE: str(environment)}, runtime,
                )
            self.assertEqual(display.socket, path)

    def test_rejects_a_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            path = runtime / "external"
            path.write_text("not a socket", encoding="utf-8")
            self.assertIsNone(discover_external_display(
                os.getuid(), {DISPLAY_VARIABLE: "external"}, runtime,
            ))
