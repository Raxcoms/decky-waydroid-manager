import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.control import ServiceControl


@unittest.skipUnless(hasattr(socket, "SO_PEERCRED"), "Requires Linux peer credentials")
class ServiceControlTests(unittest.TestCase):
    def test_service_start_is_authenticated_and_runtime_socket_is_removed(self):
        async def exercise(directory):
            starts = []
            async def start():
                starts.append(True)
            control = ServiceControl(Path(directory) / "control.sock", os.getuid(), start)
            await control.open()
            try:
                for command, expected in ((b"START\n", True), (b"STOP\n", False)):
                    reader, writer = await asyncio.open_unix_connection(str(control.path))
                    writer.write(command)
                    await writer.drain()
                    self.assertEqual(json.loads(await reader.readline())["ok"], expected)
                    writer.close()
                    await writer.wait_closed()
                control.uid += 1
                reader, writer = await asyncio.open_unix_connection(str(control.path))
                writer.write(b"START\n")
                await writer.drain()
                self.assertFalse(json.loads(await reader.readline())["ok"])
                writer.close()
                await writer.wait_closed()
                self.assertEqual(starts, [True])
            finally:
                await control.close()
            self.assertFalse(control.path.exists())
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(directory))

    def test_existing_regular_file_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.sock"
            path.write_text("user file")
            control = ServiceControl(path, os.getuid(), lambda: None)
            with self.assertRaisesRegex(RuntimeError, "occupied"):
                asyncio.run(control.open())
            self.assertEqual(path.read_text(), "user file")
