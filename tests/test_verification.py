from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.verification import InstallCancelled, InstallVerification, active_install_sessions, commit_install, verification_id, verification_dialog


REQUEST = """BroadcastRecord{abc u0 android.intent.action.PACKAGE_NEEDS_VERIFICATION} to user 0
    Intent { act=android.intent.action.PACKAGE_NEEDS_VERIFICATION dat=file:///data/app/vmdl42.tmp typ=application/vnd.android.package-archive }
      targetComp: {example.verifier/example.verifier.Receiver}
      extras: Bundle[{android.content.pm.extra.VERIFICATION_INSTALLER_UID=0, android.content.pm.extra.VERIFICATION_ID=7, android.content.pm.extra.SESSION_ID=42}]
    caller=android 305:system/1000 pid=305 uid=1000
"""
ACTIVITIES = "topResumedActivity=ActivityRecord{abc u0 example.verifier/example.PlayProtectDialogsActivity}"
ACTIVE = """Active install sessions:
  Active Session 42:
    mCommitted=true mSealed=true
    mDestroyed=false
"""
COMPLETED = """BroadcastRecord{def u0 android.intent.action.PACKAGE_VERIFIED} to user 0
    Intent { act=android.intent.action.PACKAGE_VERIFIED dat=file:///data/app/vmdl43.tmp }
      extras: Bundle[{android.content.pm.extra.VERIFICATION_ID=8, android.content.pm.extra.VERIFICATION_RESULT=1}]
    caller=android 305:system/1000 pid=305 uid=1000
"""


class VerificationRequestTests(unittest.TestCase):
    def test_warning_requires_the_configured_verifiers_blocking_activity(self):
        self.assertTrue(verification_dialog(ACTIVITIES, "example.verifier"))
        self.assertFalse(verification_dialog(ACTIVITIES.replace("PlayProtectDialogsActivity", "StoreActivity"), "example.verifier"))
        self.assertFalse(verification_dialog(ACTIVITIES, "other.verifier"))

    def test_other_pending_installs_are_ambiguous_but_finished_installs_are_not(self):
        other = REQUEST.replace("42", "43").replace("VERIFICATION_ID=7", "VERIFICATION_ID=8")
        self.assertIsNone(verification_id(REQUEST + other, "42", "example.verifier", {"42", "43"}))
        self.assertEqual(verification_id(REQUEST + other, "42", "example.verifier", {"42"}), 7)
        self.assertEqual(verification_id(REQUEST + other + COMPLETED, "42", "example.verifier", {"42", "43"}), 7)
        self.assertIsNone(verification_id(REQUEST + COMPLETED.replace("VERIFICATION_ID=8", "VERIFICATION_ID=7"), "42", "example.verifier", {"42"}))
        self.assertIsNone(verification_id(REQUEST, "42", "example.verifier", set()))

    def test_only_live_committed_sessions_can_be_waiting_for_verification(self):
        dump = ACTIVE + """  Active Session 43:
    mCommitted=false mDestroyed=false
  Active Session 44:
    mCommitted=true mDestroyed=true
  Active Session 47:
    mCommitted=true mDestroyed=true mStageDirInUse=true
Finalized install sessions:
  Active Session 45:
    mCommitted=true mDestroyed=false
Historical install sessions:
  Session 46:
    mCommitted=true mDestroyed=false
"""
        self.assertEqual(active_install_sessions(dump), {"42", "47"})

    def test_requires_owned_session_system_sender_root_installer_and_configured_provider(self):
        self.assertEqual(verification_id(REQUEST, "42", "example.verifier", {"42"}), 7)
        for text in (
            REQUEST.replace("vmdl42.tmp", "vmdl420.tmp"),
            REQUEST.replace("SESSION_ID=42", "SESSION_ID=420"),
            REQUEST.replace("INSTALLER_UID=0", "INSTALLER_UID=2000"),
            REQUEST.replace("uid=1000", "uid=10001"),
            REQUEST.replace("caller=android", "caller=example.app"),
            REQUEST.replace("example.verifier/", "other.verifier/"),
            REQUEST.replace("PACKAGE_NEEDS_VERIFICATION", "PACKAGE_NEEDS_INTEGRITY_VERIFICATION"),
        ):
            with self.subTest(text=text):
                self.assertIsNone(verification_id(text, "42", "example.verifier", {"42"}))

    def test_duplicate_history_is_accepted_but_conflicting_ids_are_rejected(self):
        self.assertEqual(verification_id(REQUEST + REQUEST, "42", "example.verifier", {"42"}), 7)
        with self.assertRaisesRegex(RuntimeError, "AMBIGUOUS"):
            verification_id(REQUEST + REQUEST.replace("VERIFICATION_ID=7", "VERIFICATION_ID=8"), "42", "example.verifier", {"42"})

    def test_ignores_incomplete_or_out_of_range_request_metadata(self):
        for value in ("-1", "unknown", "2147483648"):
            self.assertIsNone(verification_id(REQUEST.replace("VERIFICATION_ID=7", "VERIFICATION_ID=" + value), "42", "example.verifier", {"42"}))
        self.assertIsNone(verification_id(REQUEST.replace("extras:", "summary:"), "42", "example.verifier", {"42"}))


class VerificationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.directory = root / "staged"
        self.directory.mkdir()
        self.helper = root / "helper.dex"
        self.helper.write_bytes(b"dex\n")
        self.run = Mock(side_effect=self.command)
        self.commands = []
        self.identity = patch("waydroid_manager.verification.container_identity", return_value=(100, "200"))
        self.identity_mock = self.identity.start()
        self.addCleanup(self.identity.stop)
        self.bridge = InstallVerification(self.run, "42", self.helper)

    def command(self, args, **kwargs):
        self.commands.append(args)
        if args[-2:] == ["package", "verifiers"]:
            return "Required: example.verifier (uid=10123)"
        if args[-2:] == ["activity", "broadcasts"]:
            return REQUEST
        if args[-2:] == ["activity", "activities"]:
            return ACTIVITIES
        if args[-2:] == ["package", "installs"]:
            return ACTIVE
        return "VERIFICATION_SENT"

    def test_uses_dynamic_uid_and_exact_request_without_settings_or_visual_tools(self):
        self.assertTrue(self.bridge.warning_pending())
        self.bridge.respond(True)
        self.assertEqual(self.commands[:4], self.commands[4:8])
        self.assertEqual(self.commands[-2][:6], ["waydroid", "shell", "--uid", "10123", "--", "env"])
        self.assertEqual(self.commands[-2][-3:], ["waydroid.manager.InstallVerifier", "7", "2"])
        self.assertEqual(self.commands[-3][0], "lxc-attach")
        self.assertEqual(self.commands[-1][-3:-1], ["/system/bin/rm", "-rf"])

    def test_waits_for_request_and_never_guesses_an_id(self):
        self.run.side_effect = ["Required: example.verifier (uid=10123)", ACTIVITIES, ACTIVE, ""]
        self.assertFalse(self.bridge.warning_pending())
        self.assertFalse((self.directory / "verifier.dex").exists())

    def test_no_required_verifier_needs_no_helper(self):
        self.run.side_effect = None
        self.run.return_value = "Required: none"
        self.assertFalse(self.bridge.warning_pending())
        self.assertEqual(self.run.call_count, 1)

    def test_container_restart_cannot_reuse_an_old_verification_id(self):
        self.assertTrue(self.bridge.warning_pending())
        self.identity_mock.return_value = (100, "201")
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_NOT_RUNNING"):
            self.bridge.respond(True)
        self.assertFalse((self.directory / "verifier.dex").exists())

    def test_cleanup_rejects_only_its_own_active_session(self):
        other = REQUEST.replace("42", "43").replace("VERIFICATION_ID=7", "VERIFICATION_ID=8")
        active = ACTIVE + "  Active Session 43:\n    mCommitted=true mDestroyed=false\n"
        self.run.side_effect = ["Required: example.verifier (uid=10123)", active, REQUEST + other, "", "VERIFICATION_SENT", ""]
        self.bridge.reject_pending()
        self.assertEqual(self.run.call_args_list[-2].args[0][-3:], ["waydroid.manager.InstallVerifier", "7", "-1"])

    def test_finished_or_changed_request_cannot_use_an_old_approval(self):
        self.assertTrue(self.bridge.warning_pending())
        self.run.side_effect = ["Required: example.verifier (uid=10123)", ACTIVITIES, ACTIVE,
                                REQUEST.replace("VERIFICATION_ID=7", "VERIFICATION_ID=8")]
        with self.assertRaisesRegex(RuntimeError, "VERIFICATION_UNAVAILABLE"):
            self.bridge.respond(True)
        self.assertFalse((self.directory / "verifier.dex").exists())

    def test_waydroid_zero_exit_status_without_helper_marker_is_not_success(self):
        self.run.side_effect = ["Required: example.verifier (uid=10123)", ACTIVITIES, ACTIVE, REQUEST] * 2 + ["", "", ""]
        self.assertTrue(self.bridge.warning_pending())
        with self.assertRaisesRegex(RuntimeError, "VERIFICATION_UNAVAILABLE"):
            self.bridge.respond(True)


class InstallCommitTests(unittest.TestCase):
    def test_pending_commit_checks_native_verification_then_returns_package_result(self):
        process = Mock(returncode=0)
        process.communicate.side_effect = [subprocess.TimeoutExpired("pm", 1), ("Success\n", None)]
        process.poll.side_effect = [None, None, 0]
        verifier = Mock()
        confirm = Mock(return_value=True)
        with patch("waydroid_manager.verification.subprocess.Popen", return_value=process):
            self.assertEqual(commit_install(["pm"], verifier, confirm), "Success")
        verifier.respond.assert_called_once_with(True)
        confirm.assert_called_once()

    def test_ordinary_verification_never_opens_confirmation(self):
        process = Mock(returncode=0)
        process.communicate.side_effect = [subprocess.TimeoutExpired("pm", 1), ("Success\n", None)]
        process.poll.side_effect = [None, 0]
        verifier, confirm = Mock(), Mock()
        verifier.warning_pending.return_value = False
        with patch("waydroid_manager.verification.subprocess.Popen", return_value=process):
            self.assertEqual(commit_install(["pm"], verifier, confirm), "Success")
        confirm.assert_not_called()
        verifier.respond.assert_not_called()
        verifier.reject_pending.assert_not_called()

    def test_failed_commit_rejects_pending_verification_even_after_the_client_exits(self):
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code):
                process = Mock(returncode=exit_code)
                process.communicate.return_value = ("Failure [install interrupted]", None)
                process.poll.return_value = exit_code
                verifier = Mock()
                with patch("waydroid_manager.verification.subprocess.Popen", return_value=process):
                    with self.assertRaisesRegex(RuntimeError, "install interrupted"):
                        commit_install(["pm"], verifier, Mock())
                verifier.reject_pending.assert_called_once_with()
                process.communicate.assert_called_once_with(timeout=1)

    def test_declining_warning_rejects_only_that_install_and_cleans_up(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [subprocess.TimeoutExpired("pm", 1), ("", None)]
        process.poll.return_value = None
        verifier = Mock()
        with patch("waydroid_manager.verification.subprocess.Popen", return_value=process), patch("waydroid_manager.verification.os.killpg", create=True):
            with self.assertRaises(InstallCancelled):
                commit_install(["pm"], verifier, Mock(return_value=False))
        verifier.respond.assert_called_once_with(False)
        verifier.reject_pending.assert_not_called()

    def test_verification_failure_kills_owned_commit_before_abandonment(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [subprocess.TimeoutExpired("pm", 1), ("", None)]
        process.poll.return_value = None
        verifier = Mock()
        verifier.warning_pending.side_effect = RuntimeError("VERIFICATION_UNAVAILABLE")
        with patch("waydroid_manager.verification.subprocess.Popen", return_value=process), patch("waydroid_manager.verification.os.killpg", create=True) as kill:
            with self.assertRaisesRegex(RuntimeError, "VERIFICATION_UNAVAILABLE"):
                commit_install(["pm"], verifier, Mock())
            if sys.platform == "win32":
                process.kill.assert_called_once()
            else:
                self.assertEqual(kill.call_args.args[0], 123)

    def test_timeout_stops_polling_and_cleans_up(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [subprocess.TimeoutExpired("pm", 1), ("", None)]
        process.poll.return_value = None
        verifier = Mock()
        with patch("waydroid_manager.verification.subprocess.Popen", return_value=process), patch("waydroid_manager.verification.os.killpg", create=True), patch("waydroid_manager.verification.time.monotonic", side_effect=[0, 301]):
            with self.assertRaisesRegex(RuntimeError, "PACKAGE_INSTALL_TIMEOUT"):
                commit_install(["pm"], verifier, Mock())
        verifier.warning_pending.assert_not_called()
        verifier.reject_pending.assert_called_once_with()
