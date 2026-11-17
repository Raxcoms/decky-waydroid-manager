import asyncio
import unittest

from waydroid_manager.runtime_updates import RuntimeUpdates


class RuntimeUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_waits_and_events_wake_an_active_session_immediately(self):
        calls = []
        updated = asyncio.Event()
        active = False
        async def update():
            calls.append(len(calls))
            updated.set()
        watcher = RuntimeUpdates(update, lambda: active, interval=30)
        watcher.start()
        try:
            await asyncio.sleep(0)
            self.assertEqual(calls, [])
            watcher.notify()
            await asyncio.wait_for(updated.wait(), 1)
            await asyncio.sleep(0)
            self.assertEqual(len(calls), 1)
            active = True
            updated.clear()
            watcher.notify()
            await asyncio.wait_for(updated.wait(), 1)
            self.assertEqual(len(calls), 2)
            updated.clear()
            watcher.notify()
            await asyncio.wait_for(updated.wait(), 1)
            self.assertEqual(len(calls), 3)
        finally:
            await watcher.close()

