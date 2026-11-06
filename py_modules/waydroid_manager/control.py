import asyncio
import errno
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
from typing import Awaitable, Callable


def control_path(uid: int) -> Path:
    return Path(f"/run/user/{uid}/waydroid-manager-control.sock")


def request_service_start(path: Path) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(35)
        connection.connect(str(path))
        _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != 0:
            raise RuntimeError("Waydroid Manager control is not owned by its root backend")
        connection.sendall(b"START\n")
        data = bytearray()
        while not data.endswith(b"\n"):
            part = connection.recv(4096)
            if not part or len(data) + len(part) > 8192:
                raise RuntimeError("Waydroid Manager returned an invalid service response")
            data.extend(part)
        result = json.loads(data)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Could not start Waydroid"))


class ServiceControl:
    def __init__(self, path: Path, uid: int, start: Callable[[], Awaitable[None]]):
        self.path, self.uid, self.start_service = path, uid, start
        self.server = None
        self.inode = None
        self.clients = set()

    async def open(self) -> None:
        if self.path.exists() or self.path.is_symlink():
            if not stat.S_ISSOCK(self.path.lstat().st_mode):
                raise RuntimeError("Waydroid Manager control path is occupied")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(1)
                try:
                    probe.connect(str(self.path))
                except OSError as error:
                    if error.errno != errno.ECONNREFUSED:
                        raise
                else:
                    raise RuntimeError("Waydroid Manager control is already running")
            self.path.unlink()
        self.server = await asyncio.start_unix_server(self.handle, str(self.path), limit=256)
        self.path.chmod(0o600)
        os.chown(self.path, self.uid, -1)
        self.inode = self.path.lstat().st_ino

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        try:
            try:
                if len(self.clients) >= 4:
                    raise RuntimeError("Waydroid Manager service control is busy")
                self.clients.add(task)
                peer = writer.get_extra_info("socket")
                _, uid, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != self.uid or await asyncio.wait_for(reader.readline(), 5) != b"START\n":
                    raise RuntimeError("Invalid Waydroid Manager service request")
                await asyncio.wait_for(self.start_service(), 30)
                result = {"ok": True}
            except (RuntimeError, OSError, ValueError, asyncio.TimeoutError, subprocess.SubprocessError) as error:
                result = {"ok": False, "error": str(error) or "Waydroid service start timed out"}
            writer.write((json.dumps(result) + "\n").encode())
            await writer.drain()
        except OSError:
            pass
        finally:
            self.clients.discard(task)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        clients = tuple(self.clients)
        for task in clients:
            task.cancel()
        await asyncio.gather(*clients, return_exceptions=True)
        try:
            if self.path.lstat().st_ino == self.inode:
                self.path.unlink()
        except FileNotFoundError:
            pass
