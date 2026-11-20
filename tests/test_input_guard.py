from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.input_guard import guard_guest_input, wait_for_guard


class GuardReadinessTests(unittest.TestCase):
    def test_waits_for_a_complete_acknowledgement_across_pipe_reads(self):
        process = Mock()
        with patch("waydroid_manager.input_guard.select.select", return_value=([process.stdout], [], [])), \
             patch("waydroid_manager.input_guard.os.read", side_effect=[b"INPUT_GU", b"ARDED\n"]):
            wait_for_guard(process)

    def test_eof_or_timeout_never_allows_confirmation_to_open(self):
        for readable, chunk in ((True, b"Permission denied\n"), (False, b"")):
            process = Mock()
            ready = [process.stdout] if readable else []
            with self.subTest(readable=readable), \
                 patch("waydroid_manager.input_guard.select.select", return_value=(ready, [], [])), \
                 patch("waydroid_manager.input_guard.os.read", side_effect=[chunk, b""]), \
                 self.assertRaisesRegex(RuntimeError, "input guard"):
                wait_for_guard(process)


class InputGuardTests(unittest.TestCase):
    def setUp(self):
        self.identity = (100, "boot")
        self.identify = Mock(return_value=self.identity)
        self.run = Mock(return_value="Input Dispatcher State:\n  DispatchEnabled: true\n")
        self.process = Mock(returncode=0)
        self.process.__enter__ = Mock(return_value=self.process)
        self.process.__exit__ = Mock(return_value=False)
        self.process.communicate.return_value = (b"INPUT_RESTORED\n", None)
        self.spawn = patch("waydroid_manager.input_guard.subprocess.Popen", return_value=self.process)
        self.spawn_mock = self.spawn.start()
        self.addCleanup(self.spawn.stop)
        self.stage = patch("waydroid_manager.input_guard.staged_dex", return_value=nullcontext("/dev/helper.dex"))
        self.stage_mock = self.stage.start()
        self.addCleanup(self.stage.stop)
        self.wait = patch("waydroid_manager.input_guard.wait_for_guard")
        self.wait_mock = self.wait.start()
        self.addCleanup(self.wait.stop)

    def guard(self):
        return guard_guest_input(self.run, Path("helper.dex"), self.identify, self.identity)

    def test_waits_for_input_isolation_then_closes_the_pipe_to_restore_it(self):
        with self.guard():
            self.wait_mock.assert_called_once_with(self.process)
            self.process.communicate.assert_not_called()
        self.process.communicate.assert_called_once_with(timeout=10)
        command = self.spawn_mock.call_args.args[0]
        self.assertEqual(command[0], "lxc-attach")
        self.assertEqual(command[-1], "waydroid.manager.InputGuard")
        self.assertTrue(self.spawn_mock.call_args.kwargs["start_new_session"])

    def test_confirmation_failure_still_releases_the_guard(self):
        with self.assertRaisesRegex(RuntimeError, "confirmation failed"):
            with self.guard():
                raise RuntimeError("confirmation failed")
        self.process.communicate.assert_called_once_with(timeout=10)

    def test_does_not_enable_input_that_was_already_disabled(self):
        self.run.return_value = "  DispatchEnabled: false\n"
        with self.guard():
            pass
        self.stage_mock.assert_not_called()
        self.spawn_mock.assert_not_called()

    def test_refuses_to_open_confirmation_if_input_state_is_unknown(self):
        self.run.return_value = "Service input not found"
        with self.assertRaisesRegex(RuntimeError, "input dispatch state"):
            with self.guard():
                self.fail("Confirmation must not open")
        self.spawn_mock.assert_not_called()

    def test_replacement_guest_is_not_treated_as_the_original_guard(self):
        with self.guard():
            self.identify.return_value = (101, "new boot")
            self.process.communicate.return_value = (b"", None)
            self.process.returncode = 1
        self.process.communicate.assert_called_once()

    def test_missing_restore_acknowledgement_is_not_silent_success(self):
        self.process.communicate.return_value = (b"", None)
        with self.assertRaisesRegex(RuntimeError, "input restoration"):
            with self.guard():
                pass

    def test_timeout_terminates_the_guard_so_its_shutdown_hook_can_restore_input(self):
        self.process.communicate.side_effect = [subprocess.TimeoutExpired("guard", 10),
                                                (b"INPUT_RESTORED\n", None)]
        with self.guard():
            pass
        self.process.terminate.assert_called_once()
        self.process.kill.assert_not_called()
