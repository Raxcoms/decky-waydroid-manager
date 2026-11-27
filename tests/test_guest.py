from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.guest import LaunchPolicy, android_user_ready, keep_package_guest_running, package_manager_ready, set_media_volume_max


class PackageWakeTests(unittest.TestCase):
    def test_resumes_the_same_frozen_guest_during_a_package_operation(self):
        identity = (100, "boot")
        resumed = threading.Event()

        def run(command, *, timeout):
            if command[0] == "lxc-info":
                return "FROZEN"
            if command == ["waydroid", "container", "unfreeze"]:
                resumed.set()
            return ""

        with patch("waydroid_manager.guest.container_identity", return_value=identity), \
             patch("waydroid_manager.guest.process_identity", return_value=identity):
            with keep_package_guest_running(run):
                self.assertTrue(resumed.wait(2))


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


class PackageReadinessTests(unittest.TestCase):
    def test_waits_for_package_manager_to_answer_before_querying_the_verifier(self):
        run = Mock(return_value="cmd: Can't find service: package")
        self.assertFalse(package_manager_ready(run))
        run.assert_called_once()

    def test_a_configured_verifier_must_resolve_on_the_current_image(self):
        for receiver, expected in (("No receivers found", False), ("other.verifier/.Receiver", False),
                                   ("vendor.verifier/.Receiver", True)):
            with self.subTest(receiver=receiver):
                run = Mock(side_effect=["package:/system/framework/framework-res.apk",
                                        "Required: vendor.verifier (uid=10123)", receiver])
                self.assertEqual(package_manager_ready(run, verify=True), expected)
                self.assertIn("query-receivers", run.call_args.args[0])
                self.assertIn("current", run.call_args.args[0])

    def test_a_vanilla_image_with_no_required_verifier_is_supported(self):
        run = Mock(side_effect=["package:/system/framework/framework-res.apk", "Verifiers:\n"])
        self.assertTrue(package_manager_ready(run, verify=True))
        self.assertEqual(run.call_count, 2)

    def test_transient_verifier_service_errors_are_not_readiness(self):
        for output in ("Can't find service: package", "Service package not responding"):
            with self.subTest(output=output):
                run = Mock(side_effect=["package:/system/framework/framework-res.apk", output])
                self.assertFalse(package_manager_ready(run, verify=True))

    def test_operations_without_verification_only_require_package_manager(self):
        run = Mock(return_value="package:/system/framework/framework-res.apk")
        self.assertTrue(package_manager_ready(run))
        run.assert_called_once()

    def test_a_startup_command_failure_is_retried_by_the_boot_waiter(self):
        self.assertFalse(package_manager_ready(Mock(side_effect=RuntimeError("service starting"))))


class LaunchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.guest = (100, "boot")
        self.value = None
        self.writes = []
        self.activities = {"android.intent.category.LAUNCHER": ["example.app/.MainActivity"]}
        self.queries = []
        self.launch_result = None
        self.permission_activities = {}
        self.permission_queries = []
        self.now = 0.0
        self.policy = LaunchPolicy(self.run_android, lambda: self.guest, clock=lambda: self.now,
                                   sleep=lambda delay: setattr(self, "now", self.now + delay))

    def run_android(self, command, **kwargs):
        args = command[3:]
        if args[0] == "getprop":
            return ""
        if args[:3] == ["cmd", "package", "query-activities"]:
            self.queries.append(args)
            return "\n".join(self.activities.get(args[-3], []))
        if args[:3] == ["cmd", "package", "resolve-activity"]:
            self.permission_queries.append(args)
            return self.permission_activities.get(args[-1], "No activity found")
        if args == ["settings", "list", "global"]:
            return "" if self.value is None else f"policy_control={self.value}"
        self.writes.append(args)
        if args[:2] == ["am", "start"]:
            if "-W" in args:
                self.assertEqual(kwargs["timeout"], 30)
            component = args[args.index("-n") + 1] if "-n" in args else "home.app/.HomeActivity"
            return self.launch_result if self.launch_result is not None else f"Status: ok\nActivity: {component}\nComplete"
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

    def test_full_launch_targets_primary_without_expanding_notifications(self):
        self.policy.save("full")
        self.policy.present(None)
        self.assertEqual(self.writes, [
            ["setprop", "waydroid.active_apps", "Waydroid"],
            ["settings", "put", "global", "policy_control", "null*"],
            ["am", "start", "-W", "--user", "current", "--display", "0", "-a", "android.intent.action.MAIN",
             "-c", "android.intent.category.HOME"],
        ])

    def test_companion_starts_on_discovered_display_before_primary_focus(self):
        self.activities["android.intent.category.INFO"] = ["companion.app/.MainActivity"]
        self.policy.save("app")
        self.policy.present("example.app", whole_display=True, companion="companion.app", secondary_display="7")
        starts = [command for command in self.writes if command[:2] == ["am", "start"]]
        self.assertEqual([command[command.index("--display") + 1] for command in starts], ["7", "0"])
        self.assertIn("companion.app/.MainActivity", starts[0])
        self.assertIn("example.app/.MainActivity", starts[1])
        self.assertEqual(self.writes[0], ["setprop", "waydroid.active_apps", "Waydroid"])

    def test_companion_cannot_target_primary_or_full_container(self):
        self.policy.save("app")
        for package, display in ((None, "7"), ("example.app", None), ("example.app", "0")):
            with self.subTest(package=package, display=display):
                with self.assertRaisesRegex(RuntimeError, "secondary display"):
                    self.policy.present(package, companion="companion.app", secondary_display=display)
        self.assertEqual(self.writes, [])

    def test_app_launch_targets_primary_and_preserves_immersive_policy(self):
        self.policy.save("app")
        self.policy.present("example.app")
        self.assertEqual(self.writes[0], ["setprop", "waydroid.active_apps", "example.app"])
        self.assertEqual(self.writes[1][-1], "immersive.status=*")
        self.assertEqual(self.writes[2][1:8], ["start", "-W", "--user", "current", "--display", "0", "-a"])
        self.assertEqual(self.writes[2][-3:], ["-n", "example.app/.MainActivity", "--activity-reset-task-if-needed"])

    def test_launch_is_rejected_if_the_guest_has_changed(self):
        self.policy.save("app")
        self.guest = (200, "new-boot")
        with self.assertRaisesRegex(RuntimeError, "NOT_RUNNING"):
            self.policy.present("example.app")
        self.assertEqual(self.writes, [])

    def test_dual_display_app_renders_both_outputs_without_task_metadata(self):
        self.policy.save("app")
        self.policy.present("example.app", whole_display=True)
        self.assertEqual(self.writes[0], ["setprop", "waydroid.active_apps", "Waydroid"])
        self.assertEqual(self.writes[-1][-3:], ["-n", "example.app/.MainActivity", "--activity-reset-task-if-needed"])

    def test_non_default_launcher_activity_is_resolved_before_explicit_launch(self):
        self.activities = {"android.intent.category.LAUNCHER": ["example.app/.SplashActivity"]}
        self.policy.save("app")
        self.policy.present("example.app")
        self.assertEqual([query[-3] for query in self.queries],
                         ["android.intent.category.INFO", "android.intent.category.LAUNCHER"])
        self.assertIn("--components", self.queries[-1])
        self.assertEqual(self.writes[-1][-3:], ["-n", "example.app/.SplashActivity", "--activity-reset-task-if-needed"])

    def test_info_activity_takes_precedence_over_launcher(self):
        self.activities["android.intent.category.INFO"] = ["example.app/.InfoActivity"]
        self.policy.save("app")
        self.policy.present("example.app")
        self.assertEqual(len(self.queries), 1)
        self.assertIn("example.app/.InfoActivity", self.writes[-1])
        self.assertIn("android.intent.category.INFO", self.writes[-1])

    def test_missing_or_foreign_activity_does_not_change_presentation(self):
        self.activities = {"android.intent.category.LAUNCHER": ["other.package/.Activity", "No activities found"]}
        self.policy.save("app")
        with self.assertRaisesRegex(RuntimeError, "no launch activity"):
            self.policy.present("example.app")
        self.assertEqual(self.writes, [])

    def test_launch_requires_android_confirmation_of_the_requested_package(self):
        self.policy.save("app")
        for output in ("", "Status: timeout\nActivity: example.app/.MainActivity",
                       "Status: ok\nActivity: other.package/.Activity"):
            with self.subTest(output=output):
                self.launch_result = output
                with self.assertRaisesRegex(RuntimeError, "did not confirm"):
                    self.policy.present("example.app")

    def test_timed_out_splash_succeeds_only_after_the_result_activity_is_drawn(self):
        self.launch_result = "Status: timeout\nActivity: example.app/.MainActivity"
        self.policy.display_ready = Mock(side_effect=[False, True])
        self.policy.save("app")
        self.policy.present("example.app")
        self.assertEqual(self.policy.display_ready.call_args_list,
                         [unittest.mock.call("0", activity=None, package="example.app")] * 2)

    def test_timed_out_launch_stops_waiting_when_the_guest_changes(self):
        self.launch_result = "Status: timeout\nActivity: example.app/.MainActivity"
        self.policy.save("app")

        def changed(*args, **kwargs):
            self.guest = (101, "replacement")
            return False

        self.policy.display_ready = Mock(side_effect=changed)
        with self.assertRaisesRegex(RuntimeError, "did not confirm"):
            self.policy.present("example.app")
        self.policy.display_ready.assert_called_once()

    def test_timed_out_foreign_activity_does_not_use_the_drawn_fallback(self):
        self.launch_result = "Status: timeout\nActivity: other.app/.Activity"
        self.policy.display_ready = Mock(return_value=True)
        self.policy.save("app")
        with self.assertRaisesRegex(RuntimeError, "did not confirm"):
            self.policy.present("example.app")
        self.policy.display_ready.assert_not_called()

    def test_system_permission_review_keeps_the_launch_and_prompt_visible(self):
        self.permission_activities["android.intent.action.REVIEW_PERMISSIONS"] = "system.permissions/system.permissions.ReviewActivity"
        self.launch_result = "Status: ok\nActivity: system.permissions/.ReviewActivity"
        self.policy.save("app")
        self.policy.present("example.app")
        self.assertEqual(self.writes[-1], ["setprop", "waydroid.active_apps", "Waydroid"])
        self.assertIn("--user", self.permission_queries[0])
        # MATCH_SYSTEM_ONLY keeps installed apps out of permission-controller resolution.
        self.assertEqual(self.permission_queries[0][-4:], ["--query-flags", "1048576", "-a", "android.intent.action.REVIEW_PERMISSIONS"])

    def test_timed_out_permission_prompt_must_be_drawn_before_showing_it(self):
        self.permission_activities["android.intent.action.REVIEW_PERMISSIONS"] = "system.permissions/.ReviewActivity"
        self.launch_result = "Status: timeout\nActivity: system.permissions/.ReviewActivity"
        self.policy.display_ready = Mock(return_value=True)
        self.policy.save("app")
        self.policy.present("example.app")
        self.policy.display_ready.assert_called_once_with(
            "0", activity="system.permissions/.ReviewActivity", package=None)
        self.assertEqual(self.writes[-1], ["setprop", "waydroid.active_apps", "Waydroid"])

    def test_runtime_permission_prompt_uses_the_system_handler_for_this_image(self):
        self.permission_activities["android.content.pm.action.REQUEST_PERMISSIONS"] = "vendor.permissions/.GrantActivity"
        self.launch_result = "Status: ok\nActivity: vendor.permissions/vendor.permissions.GrantActivity"
        self.policy.save("app")
        self.policy.present("example.app", whole_display=True)
        self.assertEqual(len(self.permission_queries), 2)
        self.assertEqual(self.writes[-1], ["setprop", "waydroid.active_apps", "Waydroid"])

    def test_foreign_activity_is_not_accepted_as_a_permission_prompt(self):
        self.permission_activities["android.intent.action.REVIEW_PERMISSIONS"] = "system.permissions/.ReviewActivity"
        self.launch_result = "Status: ok\nActivity: other.app/.ReviewActivity"
        self.policy.save("app")
        with self.assertRaisesRegex(RuntimeError, "did not confirm"):
            self.policy.present("example.app")

    def test_normal_launch_does_not_query_permission_handlers(self):
        self.policy.save("app")
        self.policy.present("example.app")
        self.assertEqual(self.permission_queries, [])

    def test_activity_readiness_requires_matching_visible_drawn_activity(self):
        output = """Display #0 (activities):
 topResumedActivity=ActivityRecord{new u0 example.app/.MainActivity} t99}
 * Hist #0: ActivityRecord{new u0 example.app/.MainActivity} t99}
   reportedDrawn=true reportedVisible=true
"""
        self.policy.run = Mock(return_value=output)
        self.assertTrue(self.policy.display_ready("0", "example.app/example.app.MainActivity"))
        self.assertFalse(self.policy.display_ready("0", "other.app/.MainActivity"))
        self.assertFalse(self.policy.display_ready("0", "bad-component"))
        self.assertTrue(self.policy.display_ready("0", package="example.app"))
        self.assertFalse(self.policy.display_ready("0", package="other.app"))
        self.policy.run.return_value = output.replace("reportedVisible=true", "reportedVisible=false")
        self.assertFalse(self.policy.display_ready("0", "example.app/.MainActivity"))
        self.policy.run.return_value = output.replace("reportedDrawn=true", "reportedDrawn=false")
        self.assertFalse(self.policy.display_ready("0", "example.app/.MainActivity"))

    def test_external_display_readiness_requires_its_resumed_activity_to_be_drawn(self):
        output = """Display #7 (activities):
 topResumedActivity=ActivityRecord{new u0 external/.Activity} t99}
 * Hist #0: ActivityRecord{new u0 external/.Activity} t99}
   reportedDrawn=false reportedVisible=false
 * Hist #0: ActivityRecord{old u0 previous/.Activity} t98}
   reportedDrawn=true reportedVisible=true
Display #0 (activities):
 topResumedActivity=ActivityRecord{main u0 example/.Activity} t21}
"""
        self.policy.run = Mock(return_value=output)
        self.assertFalse(self.policy.display_ready("7"))
        self.policy.run.return_value = output.replace("reportedDrawn=false", "reportedDrawn=true")
        self.assertTrue(self.policy.display_ready("7"))
        self.assertFalse(self.policy.display_ready("8"))
