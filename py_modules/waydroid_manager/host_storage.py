"""Discover user storage through UDisks and watch its mount notifications."""

import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import subprocess

from .proc import clean_env
from .file_events import process_handle


SERVICE = "org.freedesktop.UDisks2"
FILESYSTEM = SERVICE + ".Filesystem"
BLOCK = SERVICE + ".Block"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"


@dataclass(frozen=True)
class HostVolume:
    identity: str
    label: str
    path: Path


def mounted_volumes(run) -> list[HostVolume]:
    output = run(["busctl", "--system", "--json=short", "call", SERVICE,
                  "/org/freedesktop/UDisks2", OBJECT_MANAGER, "GetManagedObjects"], timeout=5)
    objects = json.loads(output)["data"][0]
    result = []
    for identifier, interfaces in sorted(objects.items()):
        properties = {key: value["data"] for key, value in interfaces.get(BLOCK, {}).items()}
        if properties.get("HintSystem", True) or properties.get("HintIgnore", False):
            continue
        mounts = interfaces.get(FILESYSTEM, {}).get("MountPoints", {}).get("data", [])
        for value in mounts:
            path = Path(os.fsdecode(bytes(value).rstrip(b"\0")))
            if path.is_absolute() and path.is_dir():
                result.append(HostVolume(identifier,
                                         properties.get("IdLabel") or path.name, path.resolve()))
                break
    return result


def folder_name(label: str) -> str:
    name = re.sub(r'[/\\\x00-\x1f\x7f]', "_", label).strip().strip(".")
    return name[:100] or "Storage"


def storage_changed(message: dict) -> bool:
    data = message.get("payload", {}).get("data", [])
    member = message.get("member")
    if member in {"InterfacesAdded", "InterfacesRemoved"}:
        return len(data) == 2 and FILESYSTEM in data[1]
    if member != "PropertiesChanged" or len(data) != 3:
        return False
    interface, changed, invalidated = data
    properties = {"MountPoints"} if interface == FILESYSTEM else {"HintSystem", "HintIgnore", "IdLabel"}
    return interface in {FILESYSTEM, BLOCK} and not properties.isdisjoint((*changed, *invalidated))


class StorageMonitor:
    def __init__(self, changed):
        self.changed = changed
        self.task = None
        self.process = None
        self.handle = None

    def watch_process(self, identity):
        if identity == self.process:
            return
        self._unwatch()
        if identity is None:
            return
        try:
            handle = process_handle(identity)
        except ProcessLookupError:
            self.changed()
            return
        self.process = identity
        if handle is not None:
            self.handle = handle
            asyncio.get_running_loop().add_reader(handle, self._process_exited)

    def _unwatch(self):
        if self.handle is not None:
            asyncio.get_running_loop().remove_reader(self.handle)
            os.close(self.handle)
        self.process = self.handle = None

    def _process_exited(self):
        self._unwatch()
        self.changed()

    def start(self):
        self.task = asyncio.create_task(self._run())

    async def _run(self):
        process = None
        try:
            sender = f"type='signal',sender='{SERVICE}'"
            properties = sender + ",interface='org.freedesktop.DBus.Properties',member='PropertiesChanged'"
            lifecycle = sender + f",interface='{OBJECT_MANAGER}'"
            process = await asyncio.create_subprocess_exec(
                "busctl", "--system", "--json=short", f"--match={properties},arg0='{FILESYSTEM}'",
                f"--match={properties},arg0='{BLOCK}'", f"--match={lifecycle}", "monitor",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=clean_env())
            while line := await process.stdout.readline():
                if storage_changed(json.loads(line)):
                    self.changed()
            if await process.wait():
                raise RuntimeError("UDisks storage notifications are unavailable")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            logging.getLogger(__name__).warning("External storage updates unavailable: %s", error)
        finally:
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()

    async def close(self):
        self._unwatch()
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
