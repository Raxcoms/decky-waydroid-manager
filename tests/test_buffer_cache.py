from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class BufferCacheTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("c++"), "A host C++ compiler is needed")
    def test_release_tracking_and_bounded_eviction(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "buffer-cache")
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-I", str(root / "android/native"), str(root / "tests/buffer_cache_test.cpp"),
                            "-o", executable], check=True)
            subprocess.run([executable], check=True)
