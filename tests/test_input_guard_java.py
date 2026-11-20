from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "A Java compiler is needed")
class InputGuardJavaTests(unittest.TestCase):
    def test_closing_the_plugin_pipe_restores_input_without_a_second_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = {
                "android/os/IBinder.java": "package android.os; public interface IBinder {}",
                "android/os/ServiceManager.java": """package android.os;
                    public class ServiceManager {
                        public static IBinder getService(String name) { return null; }
                    }""",
                "android/view/IWindowManager.java": """package android.view;
                    public interface IWindowManager {
                        void setEventDispatching(boolean enabled);
                        public static class Stub {
                            public static IWindowManager asInterface(android.os.IBinder binder) {
                                return enabled -> System.err.println("DISPATCH=" + enabled);
                            }
                        }
                    }""",
            }
            paths = []
            for name, source in sources.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source)
                paths.append(str(path))
            guard = Path(__file__).resolve().parents[1] / "android/InputGuard.java"
            subprocess.run(["javac", "--release", "11", "-d", str(root), *paths, str(guard)], check=True, timeout=30)
            result = subprocess.run(["java", "-cp", str(root), "waydroid.manager.InputGuard"],
                                    input=b"", capture_output=True, timeout=10, check=True)
            self.assertEqual(result.stdout.splitlines(), [b"INPUT_GUARDED", b"INPUT_RESTORED"])
            self.assertEqual(result.stderr.splitlines(), [b"DISPATCH=false", b"DISPATCH=true"])
            if os.name == "posix":
                with subprocess.Popen(["java", "-cp", str(root), "waydroid.manager.InputGuard"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                    self.assertEqual(process.stdout.readline(), b"INPUT_GUARDED\n")
                    process.terminate()
                    _, errors = process.communicate(timeout=10)
                    self.assertEqual(errors.splitlines(), [b"DISPATCH=false", b"DISPATCH=true"])
