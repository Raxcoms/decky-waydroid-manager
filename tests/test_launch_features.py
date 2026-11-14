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
        self.plugin._runtime_display.acquire.side_effect = RuntimeError("Could not stage config")
        with (patch.object(backend, "container_pid", return_value=None),
              patch.object(backend, "discover_external_display", return_value=Mock(socket=Path("external"))),
              patch.object(backend, "inspect_vendor", return_value=Mock()),
              patch.object(backend, "select_payload", return_value={"vendor/lib.so": Path("source")})):
            with self.assertRaisesRegex(RuntimeError, "Could not stage config"):
                await self.plugin._start_registered_launch(self.launch, True)
        self.plugin._runtime_display.acquire.assert_called_once()
        self.assertIsNone(self.plugin._session_second_screen)
