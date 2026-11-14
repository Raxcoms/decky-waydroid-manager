import asyncio
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_library import backend
from waydroid_manager.control import Launch, LaunchRequest


class LaunchFeatureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = backend.Plugin()
        self.plugin._launch_lock = asyncio.Lock()
        self.plugin._user = lambda: ("user", 1000, Path("home"))
        self.state = backend.StateStore.defaults()
        self.plugin._load_state = lambda home: self.state
        self.plugin._ensure_service = AsyncMock()
        self.plugin._overlay = Mock()
        self.plugin._session_config = Mock()
        self.plugin._runtime_display = Mock()
        self.launch = Launch((1, "start"), Path("wayland"), LaunchRequest("app", "example.app"))

    async def test_standard_launch_never_stages_a_payload(self):
        await self.plugin._start_registered_launch(self.launch, True)
        self.assertFalse(self.plugin._session_second_screen)
        self.plugin._runtime_display.acquire.assert_not_called()

    async def test_join_with_different_settings_leaves_session_untouched(self):
        self.plugin._session_second_screen = False
        self.state["secondScreen"]["apps"]["example.app"] = True
        with self.assertRaisesRegex(RuntimeError, "Close the running"):
            await self.plugin._start_registered_launch(self.launch, False)
        self.plugin._ensure_service.assert_not_called()
        self.plugin._runtime_display.acquire.assert_not_called()

    async def test_plain_app_can_join_a_display_capable_session(self):
        self.plugin._session_second_screen = True
        await self.plugin._start_registered_launch(self.launch, False)
        self.assertFalse(self.plugin._display_requests[self.launch.process])
        self.plugin._ensure_service.assert_not_called()

    async def test_last_enabled_app_withdraws_display_while_plain_apps_remain(self):
        self.plugin._display_requests[self.launch.process] = True
        self.plugin._display_users.add(self.launch.process)
        self.plugin._run = Mock()
        with patch.object(backend, "session_uses_socket", return_value=True):
            await self.plugin._depart_launch(self.launch)
        self.plugin._run.assert_called_once_with([
            "waydroid", "shell", "--", "setprop", "waydroid.external_display_active", "0",
        ])

    async def test_one_enabled_app_leaving_keeps_the_other_display_lease(self):
        self.plugin._display_users.update({self.launch.process, (2, "other")})
        self.plugin._run = Mock()
        await self.plugin._depart_launch(self.launch)
        self.plugin._run.assert_not_called()

    async def test_missing_payload_does_not_stage_files(self):
        self.state["secondScreen"]["container"] = True
        with (patch.object(backend, "container_pid", return_value=None),
              patch.object(backend, "discover_external_display", return_value=Mock(socket=Path("external"))),
              patch.object(backend, "inspect_vendor", return_value=Mock()),
              patch.object(backend, "select_payload", side_effect=RuntimeError("No compatible payload"))):
            with self.assertRaisesRegex(RuntimeError, "No compatible"):
                await self.plugin._start_registered_launch(self.launch, True)
        self.plugin._runtime_display.acquire.assert_not_called()

    async def test_runtime_staging_failure_does_not_enable_the_session(self):
        self.state["secondScreen"]["container"] = True
        self.plugin._control = Mock(host=self.launch)
        self.plugin._runtime_display.acquire.side_effect = RuntimeError("Could not stage config")
        with (patch.object(backend, "container_pid", return_value=None),
              patch.object(backend, "discover_external_display", return_value=Mock(socket=Path("external"))),
              patch.object(backend, "inspect_vendor", return_value=Mock()),
              patch.object(backend, "select_payload", return_value={"vendor/lib.so": Path("source")})):
            with self.assertRaisesRegex(RuntimeError, "Could not stage config"):
                await self.plugin._start_registered_launch(self.launch, True)
        self.plugin._runtime_display.acquire.assert_called_once()
        self.plugin._control.identify_launch.assert_called_once_with(1, Path("external"))
        self.assertIsNone(self.plugin._session_second_screen)
