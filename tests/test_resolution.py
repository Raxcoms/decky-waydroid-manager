from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.resolution import launch_resolution


class LaunchResolutionTests(unittest.TestCase):
    def test_uses_inherited_game_display_instead_of_the_primary_ui_display(self):
        with patch("waydroid_manager.resolution.subprocess.run", return_value=types.SimpleNamespace(
            returncode=0, stdout="Screen 0: minimum 16 x 16, current 1280 x 720, maximum 32767 x 32767",
        )) as run:
            self.assertEqual(launch_resolution(":7"), (1280, 720))
            self.assertEqual(run.call_args.kwargs["env"]["DISPLAY"], ":7")

    def test_portrait_mode_is_already_rotated_and_must_not_be_swapped_again(self):
        with patch("waydroid_manager.resolution.subprocess.run", return_value=types.SimpleNamespace(
            returncode=0, stdout="Screen 0: current 720 x 1280\nDSI-1 connected primary 720x1280+0+0 left\n",
        )):
            self.assertEqual(launch_resolution(":2"), (720, 1280))

    def test_uses_single_active_output_instead_of_screen_extent(self):
        with patch("waydroid_manager.resolution.subprocess.run", return_value=types.SimpleNamespace(
            returncode=0, stdout="Screen 0: current 3200 x 1080\nDSI-1 connected 1280x720+0+0\nHDMI-1 connected\n",
        )):
            self.assertEqual(launch_resolution(":2"), (1280, 720))

    def test_multiple_active_outputs_leave_native_wayland_size_hints_intact(self):
        with patch("waydroid_manager.resolution.subprocess.run", return_value=types.SimpleNamespace(
            returncode=0,
            stdout="Screen 0: current 3200 x 1080\nDSI-1 connected primary 1280x720+0+0\nHDMI-1 connected 1920x1080+1280+0\n",
        )):
            self.assertIsNone(launch_resolution(":2"))

    def test_unavailable_or_invalid_modes_keep_native_compositor_hints(self):
        self.assertIsNone(launch_resolution(""))
        for output in ("", "Screen 0: current 0 x 720", "Screen 0: current 999999 x 720",
                       "Screen 0: current 1280 x 720\nDSI-1 disconnected\n"):
            with self.subTest(output=output), patch("waydroid_manager.resolution.subprocess.run", return_value=types.SimpleNamespace(returncode=0, stdout=output)):
                self.assertIsNone(launch_resolution(":1"))
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("xrandr", 3)):
            with self.subTest(error=error), patch("waydroid_manager.resolution.subprocess.run", side_effect=error):
                self.assertIsNone(launch_resolution(":1"))
