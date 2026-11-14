"""Coordinate one owned Android session and its per-launch display leases."""

import asyncio
from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
import subprocess
import time
from typing import Callable

from .container import container_identity, container_pid, session_uses_socket
from .control import Launch, ServiceControl
from .display_payload import inspect_vendor, select_payload
from .guest import GUEST_STARTING, LaunchPolicy, android_user_ready
from .proc import steam_wayland_socket
from .runtime_display import RuntimeDisplayLease
from .second_screen import discover_external_display


@dataclass
class SessionServices:
    run: Callable
    run_user: Callable
    ensure_service: Callable
    user: Callable
    enabled: Callable
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))


class LaunchSession:
    def __init__(self, config: Path, payloads: Path, services: SessionServices):
        self.config, self.payloads, self.services = config, payloads, services
        self.overlay = RuntimeDisplayLease(config)
        self.policy = LaunchPolicy(services.run, container_identity)
        self.control: ServiceControl | None = None
        self.lock = asyncio.Lock()
        self.capable: bool | None = None
        self.requests: dict[tuple[int, str], bool] = {}
        self.display_users: set[tuple[int, str]] = set()

    async def start(self, launch: Launch, owner: bool) -> None:
        async with self.lock:
            if launch.request is None:
                raise RuntimeError("The Waydroid launch request is missing")
            enabled = self.services.enabled(launch.request.package)
            if not owner:
                if self.capable is None or (enabled and not self.capable):
                    raise RuntimeError("Close the running Waydroid shortcuts before enabling the second screen")
                self.requests[launch.process] = enabled
                return
            await self.services.ensure_service()
            capable = False
            if enabled or self.payloads.is_dir():
                if container_pid() is not None:
                    if enabled:
                        raise RuntimeError("Close the running Waydroid session before enabling its second screen")
                else:
                    try:
                        _, uid, _ = self.services.user()
                        external = discover_external_display(uid, primary=steam_wayland_socket(uid))
                        if external is None:
                            raise RuntimeError("The host has no available external Wayland display")
                        identity = await asyncio.to_thread(inspect_vendor, self.config, self.services.run)
                        files = select_payload(self.payloads, identity)
                        host = self.control.host if self.control else None
                        if host is None:
                            raise RuntimeError("The shared Waydroid relay is not registered")
                        external_relay = host.display.parent / "external"
                        self.control.identify_launch(host.process[0], external_relay)
                    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                        if enabled:
                            raise
                        self.services.logger.info("Second screen unavailable for this session: %s", error)
                    else:
                        await asyncio.to_thread(self.overlay.acquire, files, external_relay,
                                                self.services.run, launch.display)
                        capable = True
            self.capable = capable
            self.requests[launch.process] = enabled

    async def depart(self, launch: Launch) -> None:
        async with self.lock:
            registered = self.requests.pop(launch.process, None) is not None
            try:
                request = launch.request
                if registered and request and request.package and self.control and session_uses_socket(launch.display):
                    shared = any(active.request and active.request.package == request.package
                                 for active in self.control.launches.values())
                    if not shared:
                        await asyncio.to_thread(self.services.run,
                                                ["waydroid", "shell", "--", "am", "force-stop", request.package])
            finally:
                if launch.process in self.display_users:
                    self.display_users.remove(launch.process)
                    if not self.display_users and session_uses_socket(launch.display):
                        await asyncio.to_thread(self.services.run, ["waydroid", "shell", "--", "setprop",
                                                                   "waydroid.external_display_active", "0"])

    async def present(self, launch: Launch, mode: str) -> None:
        async with self.lock:
            await asyncio.to_thread(self._prepare_presentation, launch, mode)

    def _prepare_presentation(self, launch: Launch, mode: str) -> None:
        if not session_uses_socket(launch.display):
            raise RuntimeError("Waydroid launch is no longer active")
        if not android_user_ready(self.services.run):
            raise RuntimeError(GUEST_STARTING)
        if self.requests.get(launch.process) and launch.process not in self.display_users:
            self.services.run(["waydroid", "shell", "--", "setprop", "waydroid.external_display_active", "1"])
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                output = self.services.run(["waydroid", "shell", "--", "cmd", "display", "get-displays",
                                            "android.hardware.display.category.PRESENTATION"], timeout=5)
                if re.search(r"Display id [1-9][0-9]*", output):
                    self.display_users.add(launch.process)
                    break
                time.sleep(0.1)
            else:
                if not self.display_users:
                    self.services.run(["waydroid", "shell", "--", "setprop", "waydroid.external_display_active", "0"])
                raise RuntimeError("Android did not connect the external display")
        self.policy.save(mode)

    async def release(self, launch: Launch) -> None:
        async with self.lock:
            try:
                await asyncio.to_thread(self._stop, launch)
            finally:
                self.capable = None
                self.requests.clear()
                self.display_users.clear()

    def _stop(self, launch: Launch) -> None:
        try:
            if session_uses_socket(launch.display):
                try:
                    self.policy.restore()
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    self.services.logger.warning("Could not restore Android display policy: %s", error)
                if session_uses_socket(launch.display):
                    self.services.run(["busctl", "--system", "--timeout=12s", "call", "id.waydro.Container",
                                       "/ContainerManager", "id.waydro.ContainerManager", "Stop", "b", "true"], timeout=15)
        finally:
            # Unit cleanup must not prevent restoring an already stopped container's mounts.
            try:
                for unit in (launch.unit, "waydroid-manager-shared-relay"):
                    try:
                        self.services.run_user(["systemctl", "--user", "is-active", "--quiet", unit], timeout=5)
                    except RuntimeError:
                        continue
                    self.services.run_user(["systemctl", "--user", "stop", "--no-block", unit], timeout=5)
            finally:
                deadline = time.monotonic() + 15
                while container_pid() is not None and time.monotonic() < deadline:
                    time.sleep(0.1)
                if container_pid() is None:
                    self.overlay.recover()
