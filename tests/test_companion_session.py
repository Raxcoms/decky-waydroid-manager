from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from waydroid_manager.control import Launch, LaunchRequest
from waydroid_manager.session import LaunchSession, SessionServices


class CompanionSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_links_are_snapshotted_only_for_enabled_app_launches(self):
        companion = Mock(return_value="other.app")
        services = SessionServices(Mock(), None, None, None, lambda package: package != "disabled.app",
                                   companion=companion)
        session = LaunchSession(Path("config"), Path("plugin"), services)
        session.capable = True
        for pid, mode, package in ((1, "app", "enabled.app"), (2, "app", "disabled.app"), (3, "full", None)):
            await session.start(Launch((pid, "start"), Path("socket"), LaunchRequest(mode, package)), False)
        companion.assert_called_once_with("enabled.app")
        companion.return_value = "changed.app"
        self.assertEqual(session.companions, {(1, "start"): "other.app"})

    async def test_departure_keeps_packages_used_by_other_launches(self):
        run = Mock()
        session = LaunchSession(Path("config"), Path("plugin"), SessionServices(run, None, None, None, None))
        first = Launch((1, "first"), Path("socket"), LaunchRequest("app", "first.app"))
        second = Launch((2, "second"), Path("socket"), LaunchRequest("app", "second.app"))
        session.control = Mock(launches={second.process: second})
        session.requests = {first.process: True, second.process: True}
        session.companions = {first.process: "second.app", second.process: "first.app"}
        with patch("waydroid_manager.session.session_uses_socket", return_value=True):
            await session.depart(first)
            run.assert_not_called()
            session.control.launches.clear()
            await session.depart(second)
        self.assertEqual([call.args[0][-1] for call in run.call_args_list], ["second.app", "first.app"])
        self.assertEqual(session.companions, {})
