import array
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.metrics import GpuMetrics, MAX_CLIENTS, MetricsSocket, android_clients, drm_identity, is_render_node


@unittest.skipUnless(hasattr(socket, "SCM_RIGHTS") and hasattr(socket, "SO_PEERCRED"), "Requires Linux descriptor passing and peer credentials")
class MetricsSocketTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.metrics = MetricsSocket(Path(self.directory.name) / "metrics", sender_uid=os.getuid())
        self.read_fd, self.write_fd = os.pipe()

    def tearDown(self):
        self.metrics.close()
        os.close(self.read_fd)
        os.close(self.write_fd)
        self.directory.cleanup()

    def transfer(self, handles, data=b"DRM1"):
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as sender:
            sender.connect(str(self.metrics.path))
            sender.sendmsg([data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", handles))] if handles else [])
            self.metrics.poll()

    def test_replaces_real_handles_and_closes_the_previous_snapshot(self):
        with patch("waydroid_manager.metrics.drm_identity", return_value=(1, "test", "2")):
            self.transfer([self.read_fd])
            held = self.metrics.handles[0]
            os.write(self.write_fd, b"actual descriptor")
            self.assertEqual(os.read(held, 17), b"actual descriptor")
            self.transfer([])
            with self.assertRaises(OSError):
                os.fstat(held)
        self.assertEqual(self.metrics.handles, [])

    def test_rejects_non_drm_handles_and_wrong_sender(self):
        self.transfer([self.read_fd])
        self.assertEqual(self.metrics.handles, [])
        self.metrics.sender_uid = os.getuid() + 1
        with patch("waydroid_manager.metrics.drm_identity", return_value=(1, "test", "2")):
            self.transfer([self.read_fd])
        self.assertEqual(self.metrics.handles, [])

    def test_truncated_or_unknown_messages_do_not_replace_valid_handles(self):
        with patch("waydroid_manager.metrics.drm_identity", return_value=(1, "test", "2")):
            self.transfer([self.read_fd])
            held = self.metrics.handles.copy()
            self.transfer([self.read_fd] * (MAX_CLIENTS + 8))
            self.transfer([], b"unknown")
        self.assertEqual(self.metrics.handles, held)
        os.fstat(held[0])

    def test_broker_verifies_the_receiving_process_before_sending(self):
        broker = GpuMetrics()
        broker.launch = (os.getpid() + 1, "unused")
        with self.assertRaises(PermissionError):
            broker.send(self.metrics.path, [], os.getuid())
        self.metrics.poll()
        broker.launch = (os.getpid(), "unused")
        stopped = threading.Event()
        def poll():
            while not stopped.is_set():
                self.metrics.poll()
                time.sleep(0.005)
        worker = threading.Thread(target=poll)
        worker.start()
        try:
            broker.send(self.metrics.path, [], os.getuid())
        finally:
            stopped.set()
            worker.join(timeout=1)

    def test_shutdown_closes_retained_handles(self):
        with patch("waydroid_manager.metrics.drm_identity", return_value=(1, "test", "2")):
            self.transfer([self.read_fd])
        held = self.metrics.handles[0]
        self.metrics.close()
        with self.assertRaises(OSError):
            os.fstat(held)

    def test_discovery_is_limited_to_android_and_deduplicates_shared_clients(self):
        root = Path(self.directory.name) / "proc"
        for pid in (10, 11, 12):
            (root / str(pid) / "ns").mkdir(parents=True)
        init_ns = root / "10/ns/pid"
        init_ns.write_text("android")
        os.link(init_ns, root / "11/ns/pid")
        (root / "12/ns/pid").write_text("host")
        for pid in (11, 12):
            for folder in ("fd", "fdinfo"):
                (root / str(pid) / folder).mkdir()
            for handle in (7, 8):
                (root / str(pid) / "fd" / str(handle)).touch()
                (root / str(pid) / "fdinfo" / str(handle)).write_text(f"drm-driver:\tmsm\ndrm-client-id:\t{pid}\n")
        original_stat = Path.stat
        device = os.makedev(226, 128)
        def fake_stat(path, *args, **kwargs):
            if path.parent.name == "fd":
                return types.SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=device)
            return original_stat(path, *args, **kwargs)
        with patch.object(Path, "stat", fake_stat):
            clients = android_clients(10, root)
        self.assertEqual(set(clients), {(device, "msm", "11")})
        pid, handle = clients[(device, "msm", "11")]
        self.assertEqual(pid, 11)
        self.assertIn(handle, (7, 8))


class MetricsIdentityTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "makedev"), "Requires Unix device identifiers")
    def test_only_render_nodes_are_allowed(self):
        for minor in (0, 64, 127, 192):
            self.assertFalse(is_render_node(types.SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=os.makedev(226, minor))))
        self.assertTrue(is_render_node(types.SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=os.makedev(226, 128))))

    def test_regular_files_are_not_gpu_handles(self):
        with tempfile.TemporaryFile() as file:
            self.assertIsNone(drm_identity(file.fileno()))
