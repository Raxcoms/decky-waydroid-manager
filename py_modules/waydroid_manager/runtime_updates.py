import asyncio
import logging
import subprocess


class RuntimeUpdates:
    """Apply events immediately and collect metrics only during an owned launch."""

    def __init__(self, update, active, interval=5.0):
        self.update, self.active, self.interval = update, active, interval
        self.changed = asyncio.Event()
        self.task = None
        self.closing = False

    def start(self):
        self.task = asyncio.create_task(self._run())

    def notify(self):
        self.changed.set()

    async def _run(self):
        last_error = None
        while not self.closing:
            await self.changed.wait()
            while not self.closing:
                self.changed.clear()
                try:
                    await self.update()
                    last_error = None
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    if str(error) != last_error:
                        logging.getLogger(__name__).warning("Runtime update unavailable: %s", error)
                    last_error = str(error)
                if not self.active():
                    break
                try:
                    await asyncio.wait_for(self.changed.wait(), self.interval)
                except asyncio.TimeoutError:
                    pass

    async def close(self):
        self.closing = True
        self.changed.set()
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
