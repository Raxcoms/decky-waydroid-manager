import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class BufferBackingTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix" and shutil.which("c++"), "Needs POSIX file descriptors and C++")
    def test_recycled_fd_and_plane_layout(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "buffer-backing"
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-I", str(root / "android/native"), str(root / "tests/buffer_backing_test.cpp"),
                            "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)
