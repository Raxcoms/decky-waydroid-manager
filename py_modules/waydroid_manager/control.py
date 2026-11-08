import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
from typing import Awaitable, Callable

from .proc import descends_from, process_identity


@dataclass(frozen=True)
class Launch:
    process: tuple[int, str]
    display: Path


def control_path(uid: int) -> Path:
    # Decky can load before logind creates the user's runtime directory.
    return Path(f"/run/waydroid-manager-control-{uid}.sock")


@contextmanager
def service_connection(path: Path, command: bytes):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(35)
        connection.connect(str(path))
        _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != 0:
            raise RuntimeError("Waydroid Manager control is not owned by its root backend")
        connection.sendall(command + b"\n")
        data = bytearray()
        while not data.endswith(b"\n"):
            part = connection.recv(4096)
            if not part or len(data) + len(part) > 8192:
                raise RuntimeError("Waydroid Manager returned an invalid service response")
            data.extend(part)
        result = json.loads(data)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Could not start Waydroid"))
        yield


def request_service_start(path: Path) -> None:
    with service_connection(path, b"START"):
        pass


class ServiceControl:
    def __init__(self, path: Path, uid: int, start: Callable[[], Awaitable[None]],
                 relay: Path | None = None, on_launch: Callable[[Launch], Awaitable[None]] | None = None,
                 on_policy: Callable[[Launch, str], Awaitable[None]] | None = None):
        self.path, self.uid, self.start_service = path, uid, start
        self.server = None
        self.inode = None
        self.clients = set()
        self.relay, self.on_launch = relay, on_launch
        self.on_policy = on_policy
        self.launch: Launch | None = None

    def identify_launch(self, pid: int, display: Path) -> Launch:
        process = Path("/proc") / str(pid)
        identity = process_identity(pid)
        args = (process / "cmdline").read_bytes().split(b"\0")
        if (not identity or not self.relay or args[1:3] != [b"-I", os.fsencode(self.relay)]
                or (process / "exe").resolve(strict=True) != Path("/usr/bin/python3").resolve(strict=True)
                or not display.is_absolute() or not display.is_socket() or display.stat().st_uid != self.uid):
            raise RuntimeError("Invalid Waydroid launch registration")
        return Launch(identity, display)

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
        launch = None
        try:
            try:
                if len(self.clients) >= 4:
                    raise RuntimeError("Waydroid Manager service control is busy")
                self.clients.add(task)
                peer = writer.get_extra_info("socket")
                pid, uid, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                command = await asyncio.wait_for(reader.readline(), 5)
                if uid != self.uid:
                    raise RuntimeError("Invalid Waydroid Manager service request")
                if command.startswith(b"LAUNCH ") and command.endswith(b"\n"):
                    if self.launch is not None:
                        raise RuntimeError("A Waydroid shortcut is already running")
                    launch = self.identify_launch(pid, Path(os.fsdecode(command[7:-1])))
                    self.launch = launch
                elif command in {b"POLICY full\n", b"POLICY app\n", b"POLICY restore\n"}:
                    if not self.launch or not self.on_policy or not descends_from(pid, self.launch.process):
                        raise RuntimeError("Waydroid launch is no longer active")
                    await self.on_policy(self.launch, command[7:-1].decode("ascii"))
                elif command != b"START\n":
                    raise RuntimeError("Invalid Waydroid Manager service request")
                if launch or command == b"START\n":
                    await asyncio.wait_for(self.start_service(), 30)
                    if launch and self.on_launch:
                        await self.on_launch(launch)
                result = {"ok": True}
            except (RuntimeError, OSError, ValueError, asyncio.TimeoutError, subprocess.SubprocessError) as error:
                result = {"ok": False, "error": str(error) or "Waydroid service start timed out"}
            writer.write((json.dumps(result) + "\n").encode())
            await writer.drain()
            if launch and result["ok"]:
                await reader.read(1)
        except OSError:
            pass
        finally:
            if launch is not None and self.launch == launch:
                if self.on_policy:
                    await self.on_policy(launch, "restore")
                self.launch = None
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
