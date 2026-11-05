import array
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin/waydroid-wayland-relay"
loader = importlib.machinery.SourceFileLoader("wayland_relay", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
relay_module = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = relay_module
loader.exec_module(relay_module)


@unittest.skipUnless(hasattr(socket, "SCM_RIGHTS"), "Requires Unix file descriptor passing")
class RelayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.parent_path = str(Path(self.directory.name) / "parent")
        self.private_path = str(Path(self.directory.name) / "private")
        self.parent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.parent.bind(self.parent_path)
        self.parent.listen()
        self.parent.settimeout(1)
        self.private = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.private.bind(self.private_path)
        self.private.listen()
        self.private.setblocking(False)
        self.relay = relay_module.Relay(self.private, self.parent_path)
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.connect(self.private_path)
        self.relay.step(0.1)
        self.host, _ = self.parent.accept()
        self.host.settimeout(1)

    def tearDown(self):
        self.relay.close()
        for connection in (self.client, self.host, self.private, self.parent):
            connection.close()
        self.directory.cleanup()

    def pump(self):
        for _ in range(4):
            self.relay.step(0.01)

    def test_bytes_and_file_descriptors_travel_in_both_directions(self):
        for sender, receiver in ((self.client, self.host), (self.host, self.client)):
            with self.subTest(sender=sender):
                read_fd, write_fd = os.pipe()
                try:
                    os.write(write_fd, b"buffer contents")
                    sender.sendmsg([b"wayland message"], [
                        (socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [read_fd])),
                    ])
                    self.pump()
                    data, ancillary, _, _ = receiver.recvmsg(128, socket.CMSG_SPACE(4))
                    self.assertEqual(data, b"wayland message")
                    descriptors = array.array("i")
                    descriptors.frombytes(ancillary[0][2])
                    try:
                        self.assertEqual(os.read(descriptors[0], 128), b"buffer contents")
                    finally:
                        relay_module.close_fds(descriptors)
                finally:
                    os.close(read_fd)
                    os.close(write_fd)

    def test_large_stream_survives_backpressure_without_reordering(self):
        payload = bytes(range(256)) * 8192
        sent = 0
        received = bytearray()
        self.client.setblocking(False)
        self.host.setblocking(False)
        deadline = time.monotonic() + 5
        while len(received) < len(payload) and time.monotonic() < deadline:
            if sent < len(payload):
                try:
                    sent += self.client.send(payload[sent:sent + 65536])
                except BlockingIOError:
                    pass
            self.relay.step(0.001)
            try:
                received.extend(self.host.recv(65536))
            except BlockingIOError:
                pass
        self.assertEqual(received, payload)

    def test_disconnect_closes_queued_descriptors(self):
        read_fd, write_fd = os.pipe()
        try:
            self.client.sendmsg([b"pending"], [
                (socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [read_fd])),
            ])
            self.relay.step(0.1)
            queued = [fd for endpoint in self.relay.endpoints for _, fds in endpoint.pending for fd in fds]
            self.assertEqual(len(queued), 1)
            self.relay.close()
            for fd in queued:
                with self.assertRaises(OSError):
                    os.fstat(fd)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_partial_writes_forward_each_descriptor_once(self):
        for endpoint in self.relay.endpoints:
            endpoint.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        payload = b"x" * 65536
        read_fd, write_fd = os.pipe()
        received = bytearray()
        descriptors = array.array("i")
        try:
            self.client.sendmsg([payload], [
                (socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [read_fd])),
            ])
            self.host.setblocking(False)
            deadline = time.monotonic() + 3
            while len(received) < len(payload) and time.monotonic() < deadline:
                self.relay.step(0.001)
                try:
                    data, ancillary, _, _ = self.host.recvmsg(65536, socket.CMSG_SPACE(16))
                    received.extend(data)
                    for _, _, value in ancillary:
                        descriptors.frombytes(value)
                except BlockingIOError:
                    pass
            self.assertEqual(received, payload)
            self.assertEqual(len(descriptors), 1)
        finally:
            relay_module.close_fds(descriptors)
            os.close(read_fd)
            os.close(write_fd)

    def test_child_exit_removes_private_socket(self):
        environment = os.environ.copy()
        environment["XDG_RUNTIME_DIR"] = self.directory.name
        result = subprocess.run(
            [sys.executable, str(SCRIPT), self.parent_path, "--", sys.executable, "-c", "pass"],
            env=environment, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(Path(self.directory.name).glob("waydroid-manager-*")), [])


if __name__ == "__main__":
    unittest.main()
