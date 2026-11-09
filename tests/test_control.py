import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import subprocess
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.control import ServiceControl


@unittest.skipUnless(hasattr(socket, "SO_PEERCRED"), "Requires Linux peer credentials")
class ServiceControlTests(unittest.TestCase):
    def test_relay_lease_uses_peer_identity_and_releases_on_disconnect(self):
        async def exercise(directory):
            root = Path(directory)
            relay = root / "relay"
            relay.write_text(
                "import socket, sys\n"
                "display = socket.socket(socket.AF_UNIX)\n"
                "display.bind(sys.argv[2])\n"
                "display.listen()\n"
                "with socket.socket(socket.AF_UNIX) as control:\n"
                "    control.connect(sys.argv[1])\n"
                "    control.sendall(sys.argv[3].encode() + b' ' + sys.argv[2].encode() + b'\\n')\n"
                "    print(control.recv(4096).decode().strip(), flush=True)\n"
                "    sys.stdin.read()\n"
            )
            async def start():
                pass
            releases = []
            async def release(launch):
                releases.append(launch)
            control = ServiceControl(root / "control.sock", os.getuid(), start, relay, on_release=release)
            await control.open()
            host = await asyncio.create_subprocess_exec(
                "/usr/bin/python3", "-I", str(relay), str(control.path), str(root / "host-wayland"), "HOST",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            )
            child = None
            try:
                response = await asyncio.wait_for(host.stdout.readline(), 5)
                self.assertEqual(json.loads(response), {"ok": True})
                child = await asyncio.create_subprocess_exec(
                    "/usr/bin/python3", "-I", str(relay), str(control.path), str(root / "wayland"), "LAUNCH",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                )
                response = await asyncio.wait_for(child.stdout.readline(), 5)
                self.assertEqual(json.loads(response)["ok"], True)
                self.assertEqual(control.launch.process[0], child.pid)
                self.assertEqual(control.launch.display, root / "host-wayland")
                with self.assertRaisesRegex(RuntimeError, "Invalid Waydroid launch"):
                    control.identify_launch(os.getpid(), root / "wayland")
            finally:
                if child:
                    child.stdin.close()
                    await asyncio.wait_for(child.wait(), 5)
                host.stdin.close()
                await asyncio.wait_for(host.wait(), 5)
                for _ in range(10):
                    if control.launch is None:
                        break
                    await asyncio.sleep(0.01)
                await control.close()
            self.assertIsNone(control.launch)
            self.assertEqual([launch.process[0] for launch in releases], [child.pid])

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(directory))

    def test_failed_service_command_returns_an_error_response(self):
        async def exercise(directory):
            async def start():
                raise subprocess.TimeoutExpired("systemctl", 30)
            control = ServiceControl(Path(directory) / "control.sock", os.getuid(), start)
            await control.open()
            try:
                reader, writer = await asyncio.open_unix_connection(str(control.path))
                writer.write(b"START\n")
                await writer.drain()
                result = json.loads(await reader.readline())
                self.assertFalse(result["ok"])
                self.assertIn("systemctl", result["error"])
                writer.close()
                await writer.wait_closed()
            finally:
                await control.close()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(directory))

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
