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

    async def test_unload_waits_for_inflight_cleanup_after_relay_disconnects(self):
        for lost_host in (False, True):
            with self.subTest(lost_host=lost_host):
                started, finish = asyncio.Event(), asyncio.Event()
                events = []

                async def cleanup(launch):
                    started.set()
                    await finish.wait()
                    events.append("stopped")

                control = ServiceControl(Path("control"), 1000, None, on_release=cleanup)
                launch = Launch((1, "first"), Path("wayland"))
                if lost_host:
                    handler = asyncio.create_task(control._release_last(launch, depart=False))
                else:
                    control.launches[launch.process] = launch
                    handler = asyncio.create_task(control.release(launch))
                control.clients.add(handler)
                await asyncio.wait_for(started.wait(), 2)
                closing = asyncio.create_task(control.close())
                await asyncio.sleep(0)
                await asyncio.gather(handler, return_exceptions=True)
                self.assertFalse(closing.done())
                finish.set()
                await asyncio.wait_for(closing, 2)
                self.assertEqual(events, ["stopped"])
