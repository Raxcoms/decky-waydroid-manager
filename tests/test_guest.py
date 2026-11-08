from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.guest import LaunchPolicy


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
