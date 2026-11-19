import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.control import Launch, ServiceControl


class SharedSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_final_release_cleans_up(self):
        released = []

        async def cleanup(launch):
            released.append(launch)

        control = ServiceControl(Path("control"), 1000, None, on_release=cleanup)
        first = Launch((1, "first"), Path("wayland"))
        second = Launch((2, "second"), Path("wayland"))
        control.launches = {first.process: first, second.process: second}
        await control.release(first)
        self.assertEqual(released, [])
        await control.release(second)
        await control.release(second)
        self.assertEqual(released, [second])
        self.assertEqual(second.unit, "waydroid-manager-shared-session")

    async def test_cancellation_keeps_cleanup_running(self):
        started, finish = asyncio.Event(), asyncio.Event()

        async def cleanup(launch):
            started.set()
            await finish.wait()

        control = ServiceControl(Path("control"), 1000, None, on_release=cleanup)
        launch = Launch((1, "first"), Path("wayland"))
        control.launches[launch.process] = launch
        release = asyncio.create_task(control.release(launch))
        await started.wait()
        release.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await release
        self.assertFalse(control.release_task.done())
        finish.set()
        await control.release_task
