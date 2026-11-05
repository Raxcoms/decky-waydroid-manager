from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.proc import clean_env


class ProcessEnvironmentTests(unittest.TestCase):
    def test_preserves_host_libraries_and_removes_bundled_python(self):
        values = {"LD_LIBRARY_PATH": "/tmp/decky", "LD_LIBRARY_PATH_ORIG": "/host/libs",
                  "PYTHONHOME": "/tmp/decky", "PYTHONPATH": "/tmp/decky", "HOME": "/home/user"}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(clean_env(), {"LD_LIBRARY_PATH": "/host/libs", "HOME": "/home/user"})
            self.assertEqual(dict(os.environ), values)

    def test_removes_bundled_search_path_without_host_override(self):
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/decky"}, clear=True):
            self.assertEqual(clean_env(), {})
