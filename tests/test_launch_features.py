import asyncio
import threading
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

import waydroid_manager.session as session
from waydroid_manager.session import LaunchSession, SessionServices
from waydroid_manager.state import StateStore
from waydroid_manager.control import Launch, LaunchRequest


class LaunchFeatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_acquisition_finishes_before_release_even_after_repeated_cancel(self):
        started, finish = threading.Event(), threading.Event()
        events = []
        self.state["secondScreen"]["apps"]["example.app"] = True
        self.plugin.control = Mock(host=self.launch)
        def acquire(*args, **kwargs):
            started.set()
            if not finish.wait(5):
                raise RuntimeError("Test did not release staging")
            events.append("acquired")
        self.plugin.overlay.acquire.side_effect = acquire
        self.plugin.overlay.recover.side_effect = lambda: events.append("recovered")
        with (patch.object(session, "container_pid", return_value=None),
              patch.object(session, "session_uses_socket", return_value=False),
              patch.object(session, "steam_wayland_socket", return_value=None),
              patch.object(session, "discover_external_display", return_value=Mock()),
              patch.object(session, "inspect_vendor", return_value=Mock()),
              patch.object(session, "prepare_payload", return_value={}),
              patch.object(session, "select_native", return_value=Mock(root=Path("native"), capabilities={"external-presentation"}))):
            task = asyncio.create_task(self.plugin.start(self.launch, True))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 3))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                cleanup = asyncio.create_task(self.plugin.release(self.launch))
                await asyncio.sleep(0)
                self.assertFalse(cleanup.done())
                self.assertEqual(events, [])
                finish.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await cleanup
                self.assertEqual(events, ["acquired", "recovered"])
            finally:
                finish.set()

    def setUp(self):
        self.state = StateStore.defaults()
        self.services = SessionServices(
            Mock(), Mock(), AsyncMock(), lambda: ("user", 1000, Path("home")),
            lambda package: StateStore.second_screen_enabled(self.state, package), Mock(),
        )
        self.plugin = LaunchSession(Path("waydroid"), Path("missing-payloads"), self.services)
        self.plugin.overlay = Mock()
        self.launch = Launch((1, "start"), Path("wayland"), LaunchRequest("app", "example.app"))

    async def test_standard_launch_never_stages_a_payload(self):
        await self.plugin.start(self.launch, True)
        self.assertFalse(self.plugin.capable)
        self.plugin.overlay.acquire.assert_not_called()

    async def test_native_limiter_can_stage_without_an_external_display(self):
        self.plugin.control = Mock(host=self.launch)
        native = Mock(root=Path("native"), capabilities={"display-frame-limit"})
        with (patch.object(Path, "is_dir", return_value=True),
              patch.object(session, "container_pid", return_value=None),
              patch.object(session, "discover_external_display", return_value=None),
              patch.object(session, "inspect_vendor", return_value=Mock()),
              patch.object(session, "select_native", return_value=native),
              patch.object(session, "prepare_payload") as resource_overlay):
            await self.plugin.start(self.launch, True)
        resource_overlay.assert_not_called()
        self.assertFalse(self.plugin.capable)
        self.assertIsNone(self.plugin.overlay.acquire.call_args.args[1])
        self.assertEqual(set(self.plugin.overlay.acquire.call_args.args[0]),
                         {f"vendor/{session.HWC_PATH}", "vendor/lib64/libhwc2on1adapter.so"})
        self.plugin.control.identify_launch.assert_not_called()

    async def test_join_with_different_settings_leaves_session_untouched(self):
        self.plugin.capable = False
        self.state["secondScreen"]["apps"]["example.app"] = True
        with self.assertRaisesRegex(RuntimeError, "Close the running"):
            await self.plugin.start(self.launch, False)
        self.plugin.services.ensure_service.assert_not_called()
        self.plugin.overlay.acquire.assert_not_called()

    async def test_plain_app_can_join_a_display_capable_session(self):
        self.plugin.capable = True
        await self.plugin.start(self.launch, False)
        self.assertFalse(self.plugin.requests[self.launch.process])
        self.plugin.services.ensure_service.assert_not_called()

    async def test_last_enabled_app_withdraws_display_while_plain_apps_remain(self):
        self.plugin.requests[self.launch.process] = True
        self.plugin.display_users.add(self.launch.process)
        self.plugin.services.run = Mock()
        with patch.object(session, "session_uses_socket", return_value=True):
            await self.plugin.depart(self.launch)
        self.plugin.services.run.assert_called_once_with([
            "waydroid", "shell", "--", "setprop", "waydroid.external_display_active", "0",
        ])

    async def test_one_enabled_app_leaving_keeps_the_other_display_lease(self):
        self.plugin.display_users.update({self.launch.process, (2, "other")})
        self.plugin.services.run = Mock()
        await self.plugin.depart(self.launch)
        self.plugin.services.run.assert_not_called()

    async def test_missing_payload_does_not_stage_files(self):
        self.state["secondScreen"]["apps"]["example.app"] = True
        with (patch.object(session, "container_pid", return_value=None),
              patch.object(session, "discover_external_display", return_value=Mock(socket=Path("external"))),
              patch.object(session, "inspect_vendor", return_value=Mock()),
              patch.object(session, "select_native", return_value=Mock(root=Path("native"))),
              patch.object(session, "prepare_payload", side_effect=RuntimeError("No compatible payload"))):
            with self.assertRaisesRegex(RuntimeError, "No compatible"):
                await self.plugin.start(self.launch, True)
        self.plugin.overlay.acquire.assert_not_called()

    async def test_incompatible_native_interface_keeps_an_ordinary_launch_on_the_fallback(self):
        native = Mock()
        native.validate_runtime.side_effect = RuntimeError("Incompatible Binder interface")
        with (patch.object(Path, "is_dir", return_value=True),
              patch.object(session, "container_pid", return_value=None),
              patch.object(session, "discover_external_display", return_value=None),
              patch.object(session, "inspect_vendor", return_value=Mock()),
              patch.object(session, "select_native", return_value=native)):
            await self.plugin.start(self.launch, True)
        self.plugin.overlay.acquire.assert_not_called()
        self.assertFalse(self.plugin.capable)

    async def test_runtime_staging_failure_does_not_enable_the_session(self):
        self.state["secondScreen"]["apps"]["example.app"] = True
        self.plugin.control = Mock(host=self.launch)
        self.plugin.overlay.acquire.side_effect = RuntimeError("Could not stage config")
        with (patch.object(session, "container_pid", return_value=None),
              patch.object(session, "discover_external_display", return_value=Mock(socket=Path("external"))),
              patch.object(session, "inspect_vendor", return_value=Mock()),
              patch.object(session, "select_native", return_value=Mock(root=Path("native"), capabilities={"external-presentation"})),
              patch.object(session, "prepare_payload", return_value={"vendor/lib.so": Path("source")})):
            with self.assertRaisesRegex(RuntimeError, "Could not stage config"):
                await self.plugin.start(self.launch, True)
        self.plugin.overlay.acquire.assert_called_once()
        files = self.plugin.overlay.acquire.call_args.args[0]
        self.assertEqual(files[f"vendor/{session.HWC_PATH}"], Path("native/hwcomposer.waydroid.so"))
        self.assertEqual(files["vendor/lib64/libhwc2on1adapter.so"], Path("native/libhwc2on1adapter.so"))
        self.plugin.control.identify_launch.assert_called_once_with(1, Path("external"))
        self.assertIsNone(self.plugin.capable)

    async def test_missing_unit_cannot_prevent_mount_recovery(self):
        self.services.run_user.side_effect = RuntimeError("Unit not loaded")
        with (patch.object(session, "session_uses_socket", return_value=False),
              patch.object(session, "container_pid", return_value=None)):
            await self.plugin.release(self.launch)
        self.plugin.overlay.recover.assert_called_once()
        self.assertIsNone(self.plugin.capable)

    async def test_session_unit_disappearing_during_stop_still_releases_relay(self):
        def run_user(args, **kwargs):
            if args[2:5] == ["stop", "--no-block", self.launch.unit]:
                raise RuntimeError("Unit not loaded")

        self.services.run_user.side_effect = run_user
        with (patch.object(session, "session_uses_socket", return_value=False),
              patch.object(session, "container_pid", return_value=None)):
            await self.plugin.release(self.launch)
        calls = [call.args[0] for call in self.services.run_user.call_args_list]
        self.assertIn(["systemctl", "--user", "stop", "--no-block", "waydroid-manager-shared-relay"], calls)
        self.plugin.overlay.recover.assert_called_once()

    async def test_failed_display_connection_rolls_back_without_recording_a_lease(self):
        self.plugin.requests[self.launch.process] = True
        self.services.run.return_value = ""
        with (patch.object(session, "session_uses_socket", return_value=True),
              patch.object(session, "android_user_ready", return_value=True),
              patch.object(session.time, "monotonic", side_effect=[0, 6])):
            with self.assertRaisesRegex(RuntimeError, "did not connect"):
                self.plugin._initialize_external(self.launch)
        self.assertEqual(self.plugin.display_users, set())
        self.assertEqual(self.services.run.call_args.args[0][-2:], ["waydroid.external_display_active", "0"])

    async def test_failed_display_connection_can_be_retried(self):
        self.plugin.requests[self.launch.process] = True
        self.plugin.policy = Mock()
        self.services.run.return_value = "Display id 7: external display"
        with (patch.object(session, "session_uses_socket", return_value=True),
              patch.object(session, "android_user_ready", return_value=True)):
            self.plugin._initialize_external(self.launch)
        self.assertEqual(self.plugin.display_users, {self.launch.process})

    async def test_dual_display_session_presents_the_app_as_a_complete_output(self):
        self.plugin.requests[self.launch.process] = True
        self.plugin.display_users.add(self.launch.process)
        self.plugin.capable = True
        self.plugin.policy = Mock()
        self.services.run.return_value = "Display id 7: external display"
        with patch.object(session, "session_uses_socket", return_value=True):
            await self.plugin.show(self.launch)
        self.plugin.policy.present.assert_called_once_with("example.app", whole_display=True, companion=None, secondary_display=None)

    async def test_departed_launch_cannot_change_the_presentation(self):
        self.plugin.policy = Mock()
        with patch.object(session, "session_uses_socket", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "no longer active"):
                await self.plugin.show(self.launch)
        self.plugin.policy.present.assert_not_called()

    async def test_preparation_initializes_android_without_exposing_the_host_window(self):
        self.plugin.requests[self.launch.process] = True
        self.plugin.policy = Mock()
        self.services.run.return_value = "Display id 7: external display"
        with (patch.object(session, "session_uses_socket", return_value=True),
              patch.object(session, "android_user_ready", return_value=True)):
            await self.plugin.present(self.launch, "app")
        self.assertIn(self.launch.process, self.plugin.display_users)
        self.assertNotIn(self.launch.process, self.plugin.presented_users)
        self.assertFalse(any(call.args[0][-2:] == ["waydroid.external_display_visible", "1"]
                             for call in self.services.run.call_args_list))
        self.plugin.policy.save.assert_called_once_with("app")

    async def test_external_display_waits_for_primary_activity_confirmation(self):
        events = []
        self.plugin.requests[self.launch.process] = True
        self.plugin.policy = Mock()
        self.plugin.policy.present.side_effect = lambda *args, **kwargs: events.append("app-ready")
        def run(command, **kwargs):
            if command[-2:] == ["waydroid.external_display_active", "1"]:
                events.append("android-initialized")
            if command[-2:] == ["waydroid.external_display_visible", "1"]:
                events.append("host-presented")
            return "Display id 7: external display"
        self.services.run.side_effect = run
        with (patch.object(session, "session_uses_socket", return_value=True),
              patch.object(session, "android_user_ready", return_value=True)):
            await self.plugin.present(self.launch, "app")
            await self.plugin.show(self.launch)
        self.assertEqual(events, ["android-initialized", "app-ready", "host-presented"])

    async def test_full_shortcut_starts_home_after_android_display_initialization(self):
        launch = Launch(self.launch.process, self.launch.display, LaunchRequest("full", None))
        self.plugin.requests[launch.process] = True
        self.plugin.policy = Mock()
        self.services.run.return_value = "Display id 7: external display"
        with (patch.object(session, "session_uses_socket", return_value=True),
              patch.object(session, "android_user_ready", return_value=True)):
            await self.plugin.present(launch, "full")
            await self.plugin.show(launch)
        self.plugin.policy.present.assert_called_once_with(None, whole_display=False, companion=None, secondary_display="7")
        self.assertIn(launch.process, self.plugin.presented_users)

    async def test_failed_primary_start_never_acquires_the_external_display(self):
        self.plugin.requests[self.launch.process] = True
        self.plugin.display_users.add(self.launch.process)
        self.plugin.policy = Mock()
        self.plugin.policy.present.side_effect = RuntimeError("Activity did not start")
        with patch.object(session, "session_uses_socket", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "did not start"):
                await self.plugin.show(self.launch)
        self.services.run.assert_not_called()
        self.assertEqual(self.plugin.presented_users, set())

    async def test_last_presented_app_hides_the_window_while_another_app_initializes(self):
        self.plugin.requests[self.launch.process] = True
        self.plugin.display_users.update({self.launch.process, (2, "pending")})
        self.plugin.presented_users.add(self.launch.process)
        with patch.object(session, "session_uses_socket", return_value=True):
            await self.plugin.depart(self.launch)
        self.services.run.assert_called_once_with([
            "waydroid", "shell", "--", "setprop", "waydroid.external_display_visible", "0",
        ])
        self.assertEqual(self.plugin.display_users, {(2, "pending")})
