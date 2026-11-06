from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.verification import InstallVerification, commit_install, verification_id


REQUEST = """BroadcastRecord{abc u0 android.intent.action.PACKAGE_NEEDS_VERIFICATION} to user 0
    Intent { act=android.intent.action.PACKAGE_NEEDS_VERIFICATION dat=file:///data/app/vmdl42.tmp typ=application/vnd.android.package-archive }
      targetComp: {example.verifier/example.verifier.Receiver}
      extras: Bundle[{android.content.pm.extra.VERIFICATION_INSTALLER_UID=0, android.content.pm.extra.VERIFICATION_ID=7, android.content.pm.extra.SESSION_ID=42}]
    caller=android 305:system/1000 pid=305 uid=1000
"""


class VerificationRequestTests(unittest.TestCase):
    def test_requires_owned_session_system_sender_root_installer_and_configured_provider(self):
        self.assertEqual(verification_id(REQUEST, "42", "example.verifier"), 7)
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
                self.assertIsNone(verification_id(text, "42", "example.verifier"))

    def test_duplicate_history_is_accepted_but_conflicting_ids_are_rejected(self):
        self.assertEqual(verification_id(REQUEST + REQUEST, "42", "example.verifier"), 7)
        with self.assertRaisesRegex(RuntimeError, "AMBIGUOUS"):
            verification_id(REQUEST + REQUEST.replace("VERIFICATION_ID=7", "VERIFICATION_ID=8"), "42", "example.verifier")

    def test_ignores_incomplete_or_out_of_range_request_metadata(self):
        for value in ("-1", "unknown", "2147483648"):
            self.assertIsNone(verification_id(REQUEST.replace("VERIFICATION_ID=7", "VERIFICATION_ID=" + value), "42", "example.verifier"))
        self.assertIsNone(verification_id(REQUEST.replace("extras:", "summary:"), "42", "example.verifier"))


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
        self.bridge = InstallVerification(self.run, "42", self.directory, "/data/local/tmp/staged", self.helper)

    def command(self, args, **kwargs):
        self.commands.append(args)
        if args[-2:] == ["package", "verifiers"]:
            return "Required: example.verifier (uid=10123)"
        if args[-2:] == ["activity", "broadcasts"]:
            return REQUEST
        return "VERIFICATION_SENT"

    def test_uses_dynamic_uid_and_exact_request_without_settings_or_visual_tools(self):
        self.bridge.approve_pending()
        self.bridge.approve_pending()
        self.assertEqual(len(self.commands), 3)
        self.assertEqual(self.commands[-1][:6], ["waydroid", "shell", "--uid", "10123", "--", "env"])
        self.assertEqual(self.commands[-1][-3:], ["waydroid.manager.InstallVerifier", "7", "2"])
        self.assertEqual((self.directory / "verifier.dex").read_bytes(), self.helper.read_bytes())

    def test_waits_for_request_and_never_guesses_an_id(self):
        self.run.side_effect = ["Required: example.verifier (uid=10123)", ""]
        self.bridge.approve_pending()
        self.assertFalse(self.bridge.approved)
        self.assertFalse((self.directory / "verifier.dex").exists())

    def test_no_required_verifier_needs_no_helper(self):
        self.run.side_effect = None
        self.run.return_value = "Required: none"
        self.bridge.approve_pending()
        self.assertEqual(self.run.call_count, 1)

    def test_container_restart_cannot_reuse_an_old_verification_id(self):
        self.identity_mock.return_value = (100, "201")
        with self.assertRaisesRegex(RuntimeError, "WAYDROID_NOT_RUNNING"):
            self.bridge.approve_pending()
        self.assertEqual(len(self.commands), 2)

    def test_waydroid_zero_exit_status_without_helper_marker_is_not_success(self):
        self.run.side_effect = ["Required: example.verifier (uid=10123)", REQUEST, ""]
        with self.assertRaisesRegex(RuntimeError, "VERIFICATION_UNAVAILABLE"):
            self.bridge.approve_pending()
        self.assertFalse(self.bridge.approved)


class InstallCommitTests(unittest.TestCase):
    def test_pending_commit_checks_native_verification_then_returns_package_result(self):
        process = Mock(returncode=0)
        process.communicate.side_effect = [subprocess.TimeoutExpired("pm", 1), ("Success\n", None)]
        process.poll.side_effect = [None, 0]
        verifier = Mock()
        with patch("waydroid_manager.verification.subprocess.Popen", return_value=process):
            self.assertEqual(commit_install(["pm"], verifier), "Success")
        verifier.approve_pending.assert_called_once()

    def test_verification_failure_kills_owned_commit_before_abandonment(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [subprocess.TimeoutExpired("pm", 1), ("", None)]
        process.poll.return_value = None
        verifier = Mock()
        verifier.approve_pending.side_effect = RuntimeError("VERIFICATION_UNAVAILABLE")
        with patch("waydroid_manager.verification.subprocess.Popen", return_value=process), patch("waydroid_manager.verification.os.killpg", create=True) as kill:
            with self.assertRaisesRegex(RuntimeError, "VERIFICATION_UNAVAILABLE"):
                commit_install(["pm"], verifier)
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
                commit_install(["pm"], verifier)
        verifier.approve_pending.assert_not_called()
