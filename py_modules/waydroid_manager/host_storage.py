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


SERVICE = "org.freedesktop.UDisks2"
FILESYSTEM = SERVICE + ".Filesystem"
BLOCK = SERVICE + ".Block"


@dataclass(frozen=True)
class HostVolume:
    identity: str
    label: str
    path: Path


def mounted_volumes(run) -> list[HostVolume]:
    output = run(["busctl", "--system", "--json=short", "call", SERVICE,
                  "/org/freedesktop/UDisks2", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"], timeout=5)
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
                result.append(HostVolume(properties.get("IdUUID") or identifier,
                                         properties.get("IdLabel") or path.name, path.resolve()))
                break
    return result


def folder_name(label: str) -> str:
    name = re.sub(r'[/\\\x00-\x1f\x7f]', "_", label).strip().strip(".")
    return name[:100] or "Storage"


class StorageMonitor:
    def __init__(self, changed):
        self.changed = changed
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self._run())

    async def _run(self):
        process = None
        try:
            match = f"type='signal',sender='{SERVICE}',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged'"
            process = await asyncio.create_subprocess_exec(
                "busctl", "--system", "--json=short", f"--match={match}", "monitor", SERVICE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=clean_env())
            while line := await process.stdout.readline():
                message = json.loads(line)
                data = message.get("payload", {}).get("data", [])
                if len(data) >= 2 and data[0] == FILESYSTEM and "MountPoints" in data[1]:
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
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
