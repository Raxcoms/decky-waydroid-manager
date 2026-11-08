from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.guest import LaunchPolicy, android_user_ready, set_media_volume_max


class MediaVolumeTests(unittest.TestCase):
    command = ["waydroid", "shell", "--", "cmd", "media_session", "volume"]

    def test_sets_and_verifies_the_reported_maximum(self):
        run = Mock(side_effect=["[V] volume is 5 in range [0..25]", "", "[V] volume is 25 in range [0..25]"])
        with patch("waydroid_manager.guest.time.sleep"):
            set_media_volume_max(run)
        self.assertEqual(run.call_args_list, [
            call([*self.command, "--get"], timeout=5),
            call([*self.command, "--set", "25"], timeout=5),
            call([*self.command, "--get"], timeout=5),
        ])

    def test_does_not_write_when_already_at_maximum(self):
        run = Mock(return_value="[V] volume is 15 in range [0..15]")
        set_media_volume_max(run)
        run.assert_called_once_with([*self.command, "--get"], timeout=5)

    def test_reports_when_android_does_not_apply_the_requested_volume(self):
        run = Mock(return_value="[V] volume is 5 in range [0..15]")
        with patch("waydroid_manager.guest.time.sleep"), self.assertRaisesRegex(RuntimeError, "did not reach"):
            set_media_volume_max(run)


class AndroidReadinessTests(unittest.TestCase):
    def test_only_explicit_boot_and_unlock_success_counts(self):
        for output, expected in (("", False), ("RUNNING_LOCKED", False), ("ANDROID_READY", True)):
            with self.subTest(output=output):
                def run(command, **kwargs):
                    self.assertIn("sys.boot_completed", command[-1])
                    self.assertIn("get-current-user", command[-1])
                    self.assertIn("get-started-user-state", command[-1])
                    self.assertEqual(kwargs["timeout"], 5)
                    return output
                self.assertEqual(android_user_ready(run), expected)


class LaunchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.guest = (100, "boot")
        self.value = None
        self.writes = []
        self.policy = LaunchPolicy(self.run_android, lambda: self.guest)

    def run_android(self, command, **kwargs):
        args = command[3:]
        if args[0] == "getprop":
            return ""
        if args == ["settings", "list", "global"]:
            return "" if self.value is None else f"policy_control={self.value}"
        self.writes.append(args)
        return ""

    def test_unset_preference_is_restored_after_a_stock_app_launch(self):
        self.policy.save("app")
        self.value = "immersive.status=*"
        self.policy.restore()
        self.assertEqual(self.writes, [["settings", "delete", "global", "policy_control"]])

    def test_existing_preference_is_restored_after_a_full_launch(self):
        self.value = "immersive.navigation=example"
        self.policy.save("full")
        self.value = "null*"
        self.policy.restore()
        self.assertEqual(self.writes, [["settings", "put", "global", "policy_control", "immersive.navigation=example"]])

    def test_restore_does_not_touch_new_guest_or_external_changes(self):
        self.policy.save("full")
        self.value = "external"
        self.policy.restore()
        self.policy.save("full")
        self.value = "null*"
        self.guest = (100, "new-boot")
        self.policy.restore()
        self.assertEqual(self.writes, [])
