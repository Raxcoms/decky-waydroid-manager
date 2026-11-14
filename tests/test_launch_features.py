import asyncio
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

import waydroid_manager.session as session
from waydroid_manager.session import LaunchSession, SessionServices
from waydroid_manager.state import StateStore
from waydroid_manager.control import Launch, LaunchRequest


class LaunchFeatureTests(unittest.IsolatedAsyncioTestCase):
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
        self.state["secondScreen"]["container"] = True
        with (patch.object(session, "container_pid", return_value=None),
              patch.object(session, "discover_external_display", return_value=Mock(socket=Path("external"))),
              patch.object(session, "inspect_vendor", return_value=Mock()),
              patch.object(session, "select_payload", side_effect=RuntimeError("No compatible payload"))):
            with self.assertRaisesRegex(RuntimeError, "No compatible"):
                await self.plugin.start(self.launch, True)
        self.plugin.overlay.acquire.assert_not_called()

    async def test_runtime_staging_failure_does_not_enable_the_session(self):
        self.state["secondScreen"]["container"] = True
        self.plugin.control = Mock(host=self.launch)
        self.plugin.overlay.acquire.side_effect = RuntimeError("Could not stage config")
        with (patch.object(session, "container_pid", return_value=None),
              patch.object(session, "discover_external_display", return_value=Mock(socket=Path("external"))),
              patch.object(session, "inspect_vendor", return_value=Mock()),
              patch.object(session, "select_payload", return_value={"vendor/lib.so": Path("source")})):
            with self.assertRaisesRegex(RuntimeError, "Could not stage config"):
                await self.plugin.start(self.launch, True)
        self.plugin.overlay.acquire.assert_called_once()
        self.plugin.control.identify_launch.assert_called_once_with(1, Path("external"))
        self.assertIsNone(self.plugin.capable)

    async def test_missing_unit_cannot_prevent_mount_recovery(self):
        self.services.run_user.side_effect = RuntimeError("Unit not loaded")
        with (patch.object(session, "session_uses_socket", return_value=False),
              patch.object(session, "container_pid", return_value=None)):
            await self.plugin.release(self.launch)
        self.plugin.overlay.recover.assert_called_once()
        self.assertIsNone(self.plugin.capable)

    async def test_failed_display_connection_rolls_back_without_recording_a_lease(self):
        self.plugin.requests[self.launch.process] = True
        self.services.run.return_value = ""
        with (patch.object(session, "session_uses_socket", return_value=True),
              patch.object(session, "android_user_ready", return_value=True),
              patch.object(session.time, "monotonic", side_effect=[0, 6])):
            with self.assertRaisesRegex(RuntimeError, "did not connect"):
                self.plugin._prepare_presentation(self.launch, "app")
        self.assertEqual(self.plugin.display_users, set())
        self.assertEqual(self.services.run.call_args.args[0][-2:], ["waydroid.external_display_active", "0"])

    async def test_failed_display_connection_can_be_retried(self):
        self.plugin.requests[self.launch.process] = True
        self.plugin.policy = Mock()
        self.services.run.return_value = "Display id 7: external display"
        with (patch.object(session, "session_uses_socket", return_value=True),
              patch.object(session, "android_user_ready", return_value=True)):
            await self.plugin.present(self.launch, "app")
        self.assertEqual(self.plugin.display_users, {self.launch.process})
        self.plugin.policy.save.assert_called_once_with("app")
