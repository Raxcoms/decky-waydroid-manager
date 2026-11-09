from contextlib import ExitStack
import os
from pathlib import Path
import stat
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.packages import apk_members, stage_apks, install_apks


class PackageSessionTests(unittest.TestCase):
    def test_split_install_uses_one_native_session_without_changing_verification_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ["base.apk", "config.arm64_v8a.apk"]
            for name in names:
                (root / name).write_bytes(b"APK")
                (root / name).chmod(0o640)
            commands = []
            def run(command, **kwargs):
                args = command[9:] if command[0] == "lxc-attach" else command[4:]
                commands.append(args)
                if args[0] == "install-write":
                    stream = kwargs["stdin"]
                    self.assertTrue(stat.S_ISFIFO(os.fstat(stream.fileno()).st_mode))
                    os.fchmod(stream.fileno(), 0o600)
                    self.assertEqual(stream.read(), b"APK")
                return "Success: created install session [42]" if args[0] == "install-create" else "Success"
            with ExitStack() as files:
                install_apks(run, {name: files.enter_context((root / name).open("rb")) for name in names})
            self.assertEqual(commands[0], ["install-create", "-r", "-S", "6"])
            self.assertEqual([command[-2:] for command in commands[1:-1]], [[name, "-"] for name in names])
            self.assertEqual(commands[-1], ["install-commit", "42"])
            self.assertFalse(any(command[0] in {"settings", "install-abandon", "install-multiple"} for command in commands))
            self.assertTrue(all(stat.S_IMODE((root / name).stat().st_mode) == 0o640 for name in names))

    def test_failed_or_timed_out_commit_abandons_only_its_session(self):
        for failure in ("Failure [INSTALL_FAILED_INVALID_APK]", subprocess.TimeoutExpired("pm", 300)):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "base.apk").write_bytes(b"APK")
                commands = []
                def run(command, **kwargs):
                    commands.append(command[4:])
                    if command[4] == "install-create":
                        return "Success: created install session [42]"
                    if command[4] == "install-commit":
                        if isinstance(failure, Exception):
                            raise failure
                        return failure
                    return "Success"
                with (root / "base.apk").open("rb") as source, self.assertRaises((RuntimeError, subprocess.TimeoutExpired)):
                    install_apks(run, {"base.apk": source})
                self.assertEqual(commands[-1], ["install-abandon", "42"])


class PackageArchiveTests(unittest.TestCase):
    def test_apk_staging_uses_the_original_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.apk"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("AndroidManifest.xml", b"manifest")
            with zipfile.ZipFile(path) as archive:
                with stage_apks(archive, apk_members(archive, ".apk")) as parts:
                    self.assertIs(parts["base.apk"], archive.fp)

    def test_split_names_cannot_collide_or_exhaust_the_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.xapk"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("one/base.apk", b"first")
                archive.writestr("two/base.apk", b"second")
            with zipfile.ZipFile(path) as archive:
                with self.assertRaisesRegex(RuntimeError, "XAPK_INVALID_NAMES"):
                    apk_members(archive, ".xapk")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("base.apk", b"first")
            with zipfile.ZipFile(path) as archive, patch("waydroid_manager.packages.shutil.disk_usage", return_value=type("Usage", (), {"free": 1})()):
                with self.assertRaisesRegex(RuntimeError, "PACKAGE_NO_SPACE"):
                    with stage_apks(archive, apk_members(archive, ".xapk"), Path(directory)):
                        self.fail("Opened package files with insufficient space")

    def test_split_staging_cleans_up_anonymous_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "app.xapk"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("base.apk", b"base")
                archive.writestr("split.apk", b"split")
            with zipfile.ZipFile(path) as archive:
                with stage_apks(archive, apk_members(archive, ".xapk"), root) as parts:
                    self.assertEqual(list(parts), ["base.apk", "split.apk"])
                    self.assertEqual(parts["base.apk"].seek(0), 0)
                    self.assertEqual(parts["base.apk"].read(), b"base")
                self.assertTrue(all(source.closed for source in parts.values()))
            self.assertEqual(list(root.iterdir()), [path])
