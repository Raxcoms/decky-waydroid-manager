from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.frame_limit import FrameLimiter


class Android:
    def __init__(self):
        self.sdk = "33"
        self.package = "example.game"
        self.uids = {"example.game": 10151, "example.browser": 10152}
        self.overrides = {10151: 50.0}
        self.writes = []

    def run(self, args):
        args = args[3:]
        if args[:1] == ["getprop"]:
            return self.sdk
        if args[:3] == ["dumpsys", "activity", "activities"]:
            return f"topResumedActivity=ActivityRecord{{abc u0 {self.package}/.MainActivity}}"
        if args[:4] == ["cmd", "package", "list", "packages"]:
            return f"package:{args[-1]} uid:{self.uids[args[-1]]}"
        if args == ["dumpsys", "SurfaceFlinger"]:
            values = ", ".join(f"[uid: {uid} frameRate: {fps:.2f} Hz]" for uid, fps in self.overrides.items())
            return "Frame Rate Overrides (backdoor): {" + values + "}"
        if args[:3] == ["service", "call", "SurfaceFlinger"]:
            uid, fps = int(args[5]), float(args[7])
            self.overrides[uid] = fps
            self.writes.append((uid, fps))
            return "Result: Parcel(NULL)"
        raise AssertionError(args)


class FrameLimitTests(unittest.TestCase):
    def setUp(self):
        self.android = Android()
        self.limiter = FrameLimiter(self.android.run)
        self.launch = (123, "456")

    def test_target_changes_apply_without_relaunching(self):
        self.limiter.sync(24, self.launch)
        self.limiter.sync(24, self.launch)
        self.limiter.sync(40, self.launch)
        self.assertEqual(self.android.writes, [(10151, 24), (10151, 40)])

    def test_disabling_restores_existing_android_override(self):
        self.limiter.sync(24, self.launch)
        self.limiter.sync(0, self.launch)
        self.assertEqual(self.android.overrides[10151], 50)

    def test_foreground_changes_and_exit_restore_each_uid(self):
        self.limiter.sync(24, self.launch)
        self.android.package = "example.browser"
        self.limiter.sync(24, self.launch)
        self.assertEqual(self.android.overrides[10152], 24)
        self.limiter.sync(24, None)
        self.assertEqual(self.android.overrides, {10151: 50, 10152: 0})

    def test_profile_changes_update_previously_seen_android_ui_as_well(self):
        self.limiter.sync(30, self.launch)
        self.android.package = "example.browser"
        self.limiter.sync(60, self.launch)
        self.assertEqual(self.android.overrides, {10151: 60, 10152: 60})
        self.limiter.sync(24, self.launch)
        self.assertEqual(self.android.overrides, {10151: 24, 10152: 24})

    def test_no_launch_does_not_contact_android(self):
        limiter = FrameLimiter(lambda args: self.fail("Android should stay untouched"))
        limiter.sync(24, None)

    def test_unverified_android_version_does_not_write(self):
        self.android.sdk = "35"
        with self.assertRaises(RuntimeError):
            self.limiter.sync(24, self.launch)
        self.assertEqual(self.android.writes, [])

    def test_container_startup_message_is_not_cached_as_android_version(self):
        self.android.sdk = "[00:01:02] WayDroid container is STOPPED"
        self.limiter.sync(24, self.launch)
        self.assertEqual(self.android.writes, [])
        self.android.sdk = "33"
        self.limiter.sync(24, self.launch)
        self.assertEqual(self.android.writes, [(10151, 24)])

    def test_activity_formats_do_not_depend_on_the_app(self):
        for value in ("topResumedActivity=", "mResumedActivity:", "ResumedActivity: "):
            with self.subTest(value=value):
                limiter = FrameLimiter(lambda args: value + "ActivityRecord{abc u0 example.browser/.Activity}")
                self.assertEqual(limiter.foreground_package(), "example.browser")


if __name__ == "__main__":
    unittest.main()
