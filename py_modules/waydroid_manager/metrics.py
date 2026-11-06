import array
import ctypes
import errno
import os
from pathlib import Path
import socket
import stat
import struct
import time

from .container import container_pid


MAX_CLIENTS = 64


def close_handles(handles: list[int]) -> None:
    for handle in handles:
        os.close(handle)


def drm_identity(handle: int) -> tuple[int, str, str] | None:
    info = os.fstat(handle)
    if not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 226:
        return None
    fields = dict(line.split(":", 1) for line in Path(f"/proc/self/fdinfo/{handle}").read_text().splitlines() if ":" in line)
    driver = fields.get("drm-driver", "").strip()
    client = fields.get("drm-client-id", "").strip()
    return (info.st_rdev, driver, client) if driver and client else None


def android_clients(init_pid: int, proc: Path = Path("/proc")) -> dict[tuple[int, str, str], tuple[int, int]]:
    namespace = (proc / str(init_pid) / "ns/pid").stat().st_ino
    clients = {}
    for process in proc.glob("[0-9]*"):
        try:
            if (process / "ns/pid").stat().st_ino != namespace:
                continue
            for entry in (process / "fd").iterdir():
                try:
                    info = entry.stat()
                    if not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 226:
                        continue
                    fields = dict(line.split(":", 1) for line in (process / "fdinfo" / entry.name).read_text().splitlines() if ":" in line)
                    driver, client = fields.get("drm-driver", "").strip(), fields.get("drm-client-id", "").strip()
                    if driver and client:
                        clients.setdefault((info.st_rdev, driver, client), (int(process.name), int(entry.name)))
                    if len(clients) >= MAX_CLIENTS:
                        return clients
                except OSError:
                    continue
        except OSError:
            continue
    return clients


def duplicate_client(pid: int, handle: int, identity: tuple[int, str, str]) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    getfd = getattr(libc, "pidfd_getfd", None)
    if getfd is None:
        raise OSError(errno.ENOSYS, "GPU metrics require pidfd_getfd")
    getfd.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    getfd.restype = ctypes.c_int
    process = os.pidfd_open(pid)
    try:
        copied = getfd(process, handle, 0)
        if copied < 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    finally:
        os.close(process)
    try:
        if drm_identity(copied) != identity:
            raise OSError(errno.ESTALE, "Android GPU client changed during discovery")
        return copied
    except BaseException:
        os.close(copied)
        raise


class MetricsSocket:
    def __init__(self, path: Path, sender_uid: int = 0):
        self.path = path
        self.sender_uid = sender_uid
        self.handles: list[int] = []
        self.pending: set[socket.socket] = set()
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.listener.bind(str(path))
        path.chmod(0o600)
        self.listener.listen(4)
        self.listener.setblocking(False)

    def poll(self) -> None:
        try:
            connection, _ = self.listener.accept()
            _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != self.sender_uid or len(self.pending) >= 4:
                connection.close()
            else:
                connection.setblocking(False)
                self.pending.add(connection)
        except BlockingIOError:
            pass
        for connection in tuple(self.pending):
            handles = []
            try:
                data, ancillary, flags, _ = connection.recvmsg(16, socket.CMSG_SPACE(MAX_CLIENTS * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
                for level, kind, value in ancillary:
                    if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                        received = array.array("i")
                        received.frombytes(value)
                        handles.extend(received)
                valid = data == b"DRM1" and not flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC)
                if valid and all(drm_identity(handle) for handle in handles):
                    close_handles(self.handles)
                    self.handles, handles = handles, []
                    connection.send(b"OK", socket.MSG_NOSIGNAL)
            except BlockingIOError:
                continue
            except OSError:
                pass
            finally:
                close_handles(handles)
            connection.close()
            self.pending.remove(connection)

    def close(self) -> None:
        for connection in self.pending:
            connection.close()
        self.pending.clear()
        close_handles(self.handles)
        self.handles.clear()
        self.listener.close()
        self.path.unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class GpuMetrics:
    def __init__(self):
        self.launch = None
        self.path = None
        self.clients = None
        self.next_scan = 0

    def send(self, path: Path, handles: list[int], uid: int) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
            connection.settimeout(0.75)
            connection.connect(str(path))
            pid, peer_uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if (pid, peer_uid) != (self.launch[0], uid):
                raise OSError(errno.EACCES, "GPU metrics socket does not belong to this launch")
            ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", handles))] if handles else []
            connection.sendmsg([b"DRM1"], ancillary)
            if connection.recv(16) != b"OK":
                raise OSError("GPU metrics relay did not acknowledge its handles")

    def sync(self, launch: tuple[int, str] | None, uid: int) -> None:
        if launch != self.launch:
            self.path = None
            self.clients = None
            self.next_scan = 0
            self.launch = launch
        if launch is None or time.monotonic() < self.next_scan:
            return
        self.next_scan = time.monotonic() + 2
        init_pid = container_pid()
        clients = android_clients(init_pid) if init_pid else {}
        if self.clients == set(clients):
            return
        handles = []
        try:
            for identity, (pid, handle) in clients.items():
                handles.append(duplicate_client(pid, handle, identity))
            if self.path is None:
                environment = (Path("/proc") / str(launch[0]) / "environ").read_bytes().split(b"\0")
                runtime = next((os.fsdecode(value.split(b"=", 1)[1]) for value in environment if value.startswith(b"XDG_RUNTIME_DIR=")), f"/run/user/{uid}")
                for path in Path(runtime).glob("waydroid-manager-*/metrics"):
                    try:
                        self.send(path, handles, uid)
                    except OSError:
                        continue
                    self.path = path
                    break
                if self.path is None:
                    return
            else:
                self.send(self.path, handles, uid)
            self.clients = set(clients)
        finally:
            close_handles(handles)

    def close(self, uid: int) -> None:
        if self.path is not None and self.launch is not None:
            try:
                self.send(self.path, [], uid)
            except OSError:
                pass
        self.path = None
        self.clients = None
