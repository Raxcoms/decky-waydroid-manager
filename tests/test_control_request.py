import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.control import ServiceControl


class LaunchRequestTests(unittest.TestCase):
    def test_accepts_a_valid_app_request(self):
        command = b"LAUNCH " + json.dumps({
            "display": "/run/user/1000/wayland", "mode": "app", "package": "example.app",
        }).encode() + b"\n"
        display, request = ServiceControl._launch_request(command)
        self.assertEqual(display, Path("/run/user/1000/wayland"))
        self.assertEqual((request.mode, request.package), ("app", "example.app"))

    def test_rejects_an_invalid_request(self):
        command = b'LAUNCH {"display":"/run/user/1000/wayland","mode":"app","package":"bad package"}\n'
        with self.assertRaisesRegex(RuntimeError, "Invalid"):
            ServiceControl._launch_request(command)
