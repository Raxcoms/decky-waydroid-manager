import unittest
from unittest.mock import Mock

from waydroid_manager.display_frame_limit import DisplayFrameLimiter, DisplayModes
from waydroid_manager.frame_limit import FrameLimiter


def display_dump(active=3, native=144, display=967):
    rates = {3: native, 9: 14, 12: 17, 29: 40, 51: 47, 88: 60}
    return f'''Display {display} (internal, primary, "Primary display")
   activeModeId={active}
   displayModes=
''' + "\n".join(f"      {{id={mode}, hwcId={mode}, resolution=1280x800, refreshRate={rate:.2f} Hz}}"
                   for mode, rate in rates.items()) + '''
Display 52 (external, "Secondary display")
   activeModeId=0
   displayModes=
      {id=0, hwcId=0, resolution=800x600, refreshRate=60.00 Hz}
'''


class DisplayFrameLimitTests(unittest.TestCase):
    def setUp(self):
        self.active = 3
        self.limit = "0"
        self.writes = []
        self.limiter = DisplayFrameLimiter(self.android)

    def android(self, *args):
        if args == ("dumpsys", "SurfaceFlinger"):
            return display_dump(self.active)
        if args == ("getprop", "waydroid.frame_limit"):
            return self.limit
        if args[:1] == ("setprop",):
            self.limit = args[2]
            return ""
        if args[:4] == ("service", "call", "SurfaceFlinger", "1035"):
            self.active = int(args[5])
            self.writes.append((int(args[7]), self.active))
            return "Result: Parcel(NULL)"
        self.fail(args)

    def test_non_divisor_uses_discovered_mode_ids(self):
        self.limiter.sync(47)
        self.limiter.sync(47)
        self.assertEqual(self.writes, [(967, 51)])
        self.assertEqual(self.limit, "47")

    def test_unchanged_caps_skip_cli_queries_and_changes_apply_immediately(self):
        now = 0.0
        android = Mock(wraps=self.android)
        limiter = DisplayFrameLimiter(android, clock=lambda: now)
        limiter.sync(47)
        android.reset_mock()
        now = 1.0
        limiter.sync(47)
        android.assert_not_called()
        limiter.sync(14)
        self.assertEqual(self.active, 9)
        self.active = 3
        now = DisplayFrameLimiter.POLICY_CHECK_INTERVAL + 2
        limiter.sync(14)
        self.assertEqual(self.active, 9)

    def test_fourteen_fps_does_not_round_to_a_refresh_divisor(self):
        self.limiter.sync(14)
        self.assertEqual(self.writes, [(967, 9)])
        self.assertEqual(self.limit, "14")

    def test_cap_clamps_to_native_and_disabling_restores_native(self):
        self.limiter.sync(17)
        self.limiter.sync(240)
        self.limiter.sync(0)
        self.assertEqual(self.writes, [(967, 12), (967, 3)])
        self.assertEqual(self.limit, "0")

    def test_external_limit_uses_requested_value_not_primary_refresh(self):
        self.limiter.sync(240)
        self.assertEqual(self.active, 3)
        self.assertEqual(self.limit, "240")

    def test_original_mode_and_property_restore(self):
        self.limit = "60"
        self.active = 88
        self.limiter.sync(40)
        self.limiter.restore()
        self.assertEqual(self.active, 88)
        self.assertEqual(self.limit, "60")

    def test_external_changes_are_not_reverted(self):
        self.limiter.sync(40)
        self.active, self.limit = 51, "47"
        self.limiter.restore()
        self.assertEqual(self.active, 51)
        self.assertEqual(self.limit, "47")

    def test_failed_mode_transaction_is_not_recorded_as_applied(self):
        android = self.limiter.android
        self.limiter.android = lambda *args: "Error" if args[0] == "service" else android(*args)
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            self.limiter.sync(40)
        self.assertIsNone(self.limiter.applied)

    def test_no_matching_primary_or_invalid_modes_fail_closed(self):
        for text in ("STOPPED", display_dump().replace("activeModeId=3", "activeModeId=999")):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                DisplayModes.primary(text)

    def test_overlay_path_does_not_limit_only_the_foreground_uid(self):
        def run(args):
            command = tuple(args[3:])
            if command == ("getprop", "ro.build.version.sdk"):
                return "33"
            if command == ("getprop", "waydroid.frame_limit_modes"):
                return "1"
            return self.android(*command)

        guest = (100, "boot")
        limiter = FrameLimiter(run, lambda: guest)
        limiter.sync(47, (200, "launch"), guest)
        self.assertEqual(self.active, 51)
        self.assertEqual(limiter.applied, {})
        # A replacement guest must never receive the old display mode or property.
        guest = (101, "new-boot")
        limiter.restore()
        self.assertEqual(self.active, 51)
        self.assertEqual(self.limit, "47")
