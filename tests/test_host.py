import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from waydroid_manager.host import default_launch_options, launch_wrapper, updated_launch_options


class HostIntegrationTests(unittest.TestCase):
    def test_existing_custom_options_and_wrappers_are_preserved(self):
        with patch("waydroid_manager.host.launch_wrapper", return_value=Path("/host/wrapper")):
            for options in ("CUSTOM=1 %command% full", "gamescope --hdr-enabled -- %command% full",
                            "/host/wrapper %command% app example.app", '"unterminated'):
                self.assertIsNone(updated_launch_options(options))

    def test_only_plain_plugin_options_gain_the_available_wrapper(self):
        with patch("waydroid_manager.host.launch_wrapper", return_value=Path("/host tools/wrapper")):
            self.assertEqual(updated_launch_options("app example.app"),
                             "'/host tools/wrapper' %command% app example.app")
            self.assertEqual(default_launch_options("full"), "'/host tools/wrapper' %command% full")
        with patch("waydroid_manager.host.launch_wrapper", return_value=None):
            self.assertIsNone(updated_launch_options("full"))
            self.assertEqual(default_launch_options("full"), "full")

    def test_host_prefix_is_discovered_instead_of_assuming_a_device_path(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            wrapper = prefix / "libexec/armada/armada-game-launch"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("#!/bin/sh\n")
            wrapper.chmod(0o755)
            with patch("waydroid_manager.host.shutil.which", side_effect=[None, str(prefix / "bin/systemd-run")]):
                self.assertEqual(launch_wrapper(), wrapper)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux shell tools")
    def test_native_environment_preserves_host_settings_without_values_in_arguments(self):
        helper = Path(__file__).resolve().parents[1] / "bin/waydroid-runtime-env"
        environment = {**os.environ, "ARMADA_TEST": 'spaces $literal "quotes"', "LD_LIBRARY_PATH": "/foreign/runtime",
                       "PYTHONPATH": "/foreign/python", "ENABLE_GAMESCOPE_WSI": "1", "CUSTOM_HDR_SETTING": "1"}
        result = subprocess.run(["bash", "-c", 'source "$1"; printf "%s\\0" "${runtime_environment[@]}"; env -0',
                                 "test", str(helper)], env=environment, capture_output=True, check=True)
        values = result.stdout.decode().split("\0")
        self.assertIn("--setenv=ARMADA_TEST", values)
        self.assertIn("ARMADA_TEST=" + environment["ARMADA_TEST"], values)
        self.assertIn("ENABLE_GAMESCOPE_WSI=1", values)
        self.assertIn("CUSTOM_HDR_SETTING=1", values)
        self.assertNotIn("--setenv=LD_LIBRARY_PATH", values)
        self.assertNotIn("--setenv=PYTHONPATH", values)
        self.assertFalse(any(value.startswith("--setenv=ARMADA_TEST=") for value in values))
