from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import sys
import threading
import tempfile
import unittest
from unittest.mock import Mock, patch

from waydroid_manager.runtime_display import RuntimeDisplayLease, guard, stop_owned_guest


class StagingCleanupTests(unittest.TestCase):
    def test_recovery_preserves_data_if_staging_contains_a_mount(self):
        for manifest in (None, "[]"):
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "runtime space"
                (root / "view/Home").mkdir(parents=True)
                sentinel = root / "view/Home/sentinel"
                sentinel.write_text("must remain")
                if manifest:
                    (root / "mounts.json").write_text(manifest)
                original = Path.read_text
                target = str(sentinel.parent).replace(" ", "\\040")

                def read(path, *args, **kwargs):
                    if str(path) == "/proc/self/mountinfo":
                        return f"123 1 0:1 / {target} rw - tmpfs tmpfs rw\n"
                    return original(path, *args, **kwargs)

                with patch.object(Path, "read_text", read):
                    with self.assertRaisesRegex(RuntimeError, "still contains a mount"):
                        RuntimeDisplayLease(Path(directory), root).recover()
                self.assertEqual(sentinel.read_text(), "must remain")

    def test_unmounted_staging_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir()
            (root / "owned-file").write_text("temporary")
            RuntimeDisplayLease(Path(directory), root).recover()
            self.assertFalse(root.exists())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux file locks")
    def test_guard_waits_for_release_and_recovers_only_an_abandoned_lease(self):
        import fcntl
        for crashed in (False, True):
            with self.subTest(crashed=crashed), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                lease = RuntimeDisplayLease(base, base / "runtime")
                lease.root.mkdir()
                display = base / "wayland"
                display.touch()
                lease.start_guard(Mock(), display)
                self.assertFalse(os.get_inheritable(lease.owner.fileno()))
                script = Path(lease.owner.name)
                display_id = display.stat().st_dev, display.stat().st_ino
                waiting = threading.Event()
                flock = fcntl.flock

                def enter(file, operation):
                    if Path(file.name) == script:
                        waiting.set()
                    return flock(file, operation)

                with (ThreadPoolExecutor(max_workers=1) as pool,
                      patch.object(fcntl, "flock", side_effect=enter),
                      patch("waydroid_manager.runtime_display.stop_owned_guest") as stop):
                    future = pool.submit(guard, script, base, display_id)
                    try:
                        self.assertTrue(waiting.wait(2))
                        self.assertFalse(future.done())
                        if crashed:
                            lease.owner.close()
                        else:
                            lease.recover()
                    finally:
                        if lease.owner is not None:
                            lease.owner.close()
                    future.result(timeout=3)
                    if crashed:
                        stop.assert_called_once_with(base, display_id)
                    else:
                        stop.assert_not_called()
                    self.assertFalse(lease.root.exists())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux file locks")
    def test_stale_guard_cannot_touch_a_new_generation_at_the_same_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mounts.json").write_text("[]")
            with patch("waydroid_manager.runtime_display.stop_owned_guest") as stop:
                RuntimeDisplayLease(root, root).recover(root / "guard-from-old-session.py", (1, 2))
                stop.assert_not_called()
            self.assertTrue((root / "mounts.json").is_file())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux mount identities")
    def test_only_the_visible_mount_can_be_released(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "overlay space"
            target.mkdir()
            lease = RuntimeDisplayLease(root, root / "lease")
            lease.root.mkdir()
            escaped = str(target).replace(" ", r"\040")
            records = (f"10 1 0:1 / {escaped} ro - overlay overlay ro,lowerdir={lease.root}/overlay:{escaped}\n"
                       f"17 10 0:5 / {escaped} ro - overlay overlay ro,lowerdir=/replacement\n")
            lease._save([{"target": str(target), "previous": None, "applied": "10"}])
            original = Path.read_text

            def read(path, *args):
                if str(path) == "/proc/self/mountinfo":
                    return records
                if str(path).startswith("/proc/self/fdinfo/"):
                    return "mnt_id:\t17\n"
                return original(path, *args)

            with patch.object(Path, "read_text", read), patch("subprocess.run") as run:
                with self.assertRaisesRegex(RuntimeError, "runtime mount changed"):
                    lease.recover()
                run.assert_not_called()
                self.assertTrue(lease.manifest.is_file())

    def test_guard_stops_only_a_guest_with_the_recorded_relay_socket(self):
        for actual in ((1, 2), (1, 3), (2, 2)):
            with self.subTest(actual=actual):
                with (patch("waydroid_manager.runtime_display.subprocess.run",
                            return_value=Mock(returncode=0, stdout="42")) as run,
                      patch.object(Path, "stat", return_value=Mock(st_dev=actual[0], st_ino=actual[1]))):
                    stop_owned_guest(Path("config"), (1, 2))
                    self.assertEqual([call.args[0][0] for call in run.call_args_list],
                                     ["lxc-info", "busctl"] if actual == (1, 2) else ["lxc-info"])
