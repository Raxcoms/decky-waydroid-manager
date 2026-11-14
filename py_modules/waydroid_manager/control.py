import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import json
import logging
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import re
from typing import Awaitable, Callable

from .proc import descends_from, process_identity


@dataclass(frozen=True)
class LaunchRequest:
    mode: str
    package: str | None


@dataclass(frozen=True)
class Launch:
    process: tuple[int, str]
    display: Path
    request: LaunchRequest | None = None

    @property
    def unit(self) -> str:
        return "waydroid-manager-shared-session"


@dataclass
class ServiceConnection:
    socket: socket.socket
    result: dict

    def fileno(self) -> int:
        return self.socket.fileno()


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
        yield ServiceConnection(connection, result)


def request_service_start(path: Path) -> None:
    with service_connection(path, b"START"):
        pass


class ServiceControl:
    def __init__(self, path: Path, uid: int, start: Callable[[], Awaitable[None]],
                 relay: Path | None = None, on_launch: Callable[[Launch], Awaitable[None]] | None = None,
                 on_policy: Callable[[Launch, str], Awaitable[None]] | None = None,
                 on_release: Callable[[Launch], Awaitable[None]] | None = None,
                 start_launch: Callable[[Launch, bool], Awaitable[None]] | None = None):
        self.path, self.uid, self.start_service = path, uid, start
        self.server = None
        self.inode = None
        self.clients = set()
        self.relay, self.on_launch = relay, on_launch
        self.on_policy, self.on_release = on_policy, on_release
        self.start_launch = start_launch
        self.host: Launch | None = None
        self.launches: dict[tuple[int, str], Launch] = {}
        self.release_task: asyncio.Task | None = None

    @property
    def launch(self) -> Launch | None:
        return next(iter(self.launches.values()), None)

    def _launch_for_pid(self, pid: int) -> Launch | None:
        return next((launch for launch in self.launches.values() if descends_from(pid, launch.process)), None)

    async def release(self, launch: Launch) -> None:
        if self.launches.pop(launch.process, None) is None or self.launches:
            return
        if not self.on_release:
            return
        if self.release_task is None:
            self.release_task = asyncio.create_task(self.on_release(launch))
        await asyncio.shield(self.release_task)

    def identify_launch(self, pid: int, display: Path) -> Launch:
        process = Path("/proc") / str(pid)
        identity = process_identity(pid)
        args = (process / "cmdline").read_bytes().split(b"\0")
        if (not identity or not self.relay or args[1:3] != [b"-I", os.fsencode(self.relay)]
                or (process / "exe").resolve(strict=True) != Path("/usr/bin/python3").resolve(strict=True)
                or not display.is_absolute() or not display.is_socket() or display.stat().st_uid != self.uid):
            raise RuntimeError("Invalid Waydroid launch registration")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            probe.connect(str(display))
            owner, _, _ = struct.unpack("3i", probe.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if owner != pid:
                raise RuntimeError("The Waydroid relay does not own its registered socket")
        return Launch(identity, display)

    @staticmethod
    def _launch_request(command: bytes) -> tuple[Path, LaunchRequest]:
        try:
            value = json.loads(command[7:-1])
            display = Path(value["display"])
            mode = value["mode"]
            package = value.get("package")
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("Invalid Waydroid launch request") from error
        if mode == "full" and package is None:
            return display, LaunchRequest(mode, None)
        if (mode == "app" and isinstance(package, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", package)):
            return display, LaunchRequest(mode, package)
        raise RuntimeError("Invalid Waydroid launch request")

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
        self.server = await asyncio.start_unix_server(self.handle, str(self.path), limit=8192)
        self.path.chmod(0o600)
        os.chown(self.path, self.uid, -1)
        self.inode = self.path.lstat().st_ino

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        launch = None
        host = None
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
                if command.startswith(b"HOST ") and command.endswith(b"\n"):
                    if self.host is not None:
                        raise RuntimeError("The shared Waydroid relay is already running")
                    host = self.identify_launch(pid, Path(os.fsdecode(command[5:-1])))
                    self.host = host
                elif command.startswith(b"LAUNCH ") and command.endswith(b"\n"):
                    if self.release_task is not None:
                        raise RuntimeError("Waydroid launch is closing. Try again after it stops.")
                    if self.host is None:
                        raise RuntimeError("The shared Waydroid relay is not ready")
                    owner = not self.launches
                    display, request = self._launch_request(command)
                    registered = self.identify_launch(pid, display)
                    launch = Launch(registered.process, self.host.display, request)
                    self.launches[launch.process] = launch
                elif command in {b"POLICY full\n", b"POLICY app\n", b"RELEASE\n"}:
                    active = self._launch_for_pid(pid)
                    if active is None:
                        raise RuntimeError("Waydroid launch is no longer active")
                    if command == b"RELEASE\n":
                        await self.release(active)
                    elif self.on_policy and self.release_task is None:
                        await self.on_policy(active, command[7:-1].decode("ascii"))
                    else:
                        raise RuntimeError("Waydroid launch is closing")
                elif command != b"START\n":
                    raise RuntimeError("Invalid Waydroid Manager service request")
                if launch or command == b"START\n":
                    if launch and self.start_launch:
                        await asyncio.wait_for(self.start_launch(launch, owner), 30)
                    else:
                        await asyncio.wait_for(self.start_service(), 30)
                    if launch and owner and self.on_launch:
                        await self.on_launch(launch)
                result = {"ok": True}
                if launch:
                    if self.host is None or launch.process not in self.launches:
                        raise RuntimeError("The shared Waydroid relay stopped during startup")
                    result.update(owner=owner, display=str(launch.display))
            except (RuntimeError, OSError, ValueError, asyncio.TimeoutError, subprocess.SubprocessError) as error:
                result = {"ok": False, "error": str(error) or "Waydroid service start timed out"}
            writer.write((json.dumps(result) + "\n").encode())
            await writer.drain()
            if (launch or host) and result["ok"]:
                await reader.read(1)
        except OSError:
            pass
        finally:
            if launch is not None:
                try:
                    await self.release(launch)
                except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                    logging.getLogger(__name__).warning("Could not release the Waydroid launch: %s", error)
            if host is not None and self.host == host:
                self.host = None
                if self.launches:
                    launches = tuple(self.launches.values())
                    self.launches.clear()
                    try:
                        if self.on_release:
                            await self.on_release(launches[0])
                    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                        logging.getLogger(__name__).warning("Could not stop the lost Waydroid relay: %s", error)
            if not self.launches and self.release_task is not None and self.release_task.done():
                self.release_task = None
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
