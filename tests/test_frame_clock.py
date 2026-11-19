from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class FrameClockTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("c++"), "A host C++ compiler is needed")
    def test_independent_deadlines_and_late_frames(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "frame-clock")
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-I", str(root / "android/native"), str(root / "tests/frame_clock_test.cpp"),
                            "-o", executable], check=True)
            subprocess.run([executable], check=True)
