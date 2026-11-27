from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class ReleaseGateTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("c++"), "A host C++ compiler is needed")
    def test_release_waits_and_buffer_reuse(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "release-gate")
            subprocess.run(["c++", "-std=c++17", "-pthread", "-Wall", "-Wextra", "-Werror",
                            "-I", str(root / "android/native"), str(root / "tests/release_gate_test.cpp"),
                            "-o", executable], check=True)
            subprocess.run([executable], check=True)
