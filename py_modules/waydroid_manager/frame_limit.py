import math
import re
import subprocess
from typing import Callable
from .container import container_identity
from .display_frame_limit import DisplayFrameLimiter


class FrameLimiter:
    def __init__(self, run: Callable[[list[str]], str], identify=container_identity):
        self.run = run
        self.identify = identify
        self.guest = None
        self.launch = None
        self.original: dict[int, float] = {}
        self.applied: dict[int, float] = {}
        self.package_uids: dict[str, int] = {}
        self.sdk = None
        self.display_modes = None
        self.display_limiter = DisplayFrameLimiter(self.owned_android)

    def owned_android(self, *command: str) -> str:
        if self.identify() != self.guest:
            raise RuntimeError("The Waydroid guest changed")
        return self.android(*command)

    def android(self, *command: str) -> str:
        return self.run(["waydroid", "shell", "--", *command])

    def foreground_package(self) -> str | None:
        output = self.android("dumpsys", "activity", "activities")
        match = re.search(r"(?:topResumedActivity|mResumedActivity|ResumedActivity)\s*[:=]\s*.*?\bu\d+\s+([A-Za-z0-9._]+)/", output)
        return match.group(1) if match else None

    def package_uid(self, package: str) -> int | None:
        output = self.android("cmd", "package", "list", "packages", "--user", "current", "-U", package)
        match = re.search(rf"^package:{re.escape(package)}\s+uid:(\d+)$", output, re.MULTILINE)
        return int(match.group(1)) if match else None

    def override(self, uid: int, fps: float) -> None:
        if self.identify() != self.guest:
            raise RuntimeError("The Waydroid guest changed")
        # Android 13's SurfaceFlinger exposes a temporary per-UID frame-rate override.
        result = self.android("service", "call", "SurfaceFlinger", "1039", "i32", str(uid), "f", str(fps))
        if "Parcel(NULL)" not in result:
            raise RuntimeError("Android rejected the app frame limit")

    def compatible_rate(self, target: int) -> float | None:
        period, _, _ = self.android("dumpsys", "SurfaceFlinger", "--latency").partition("\n")
        period = period.strip()
        if not period.isdecimal() or not 1_000_000 <= int(period) <= 1_000_000_000:
            return None
        refresh = round(1_000_000_000 / int(period), 4)
        # A one-FPS difference at native refresh should not halve the frame rate.
        if target >= round(refresh) - 1:
            return refresh
        # Android needs a whole number of refresh periods. Steam rounds the displayed cap.
        divisor = max(1, math.ceil(refresh / (target + min(0.4999, target * 0.01))))
        return refresh / divisor

    def overrides(self) -> dict[int, float]:
        output = self.android("dumpsys", "SurfaceFlinger")
        section = re.search(r"Frame Rate Overrides \(backdoor\):[^\n]*", output)
        if not section:
            raise RuntimeError("Could not read Android's existing frame-rate overrides")
        return {int(uid): float(fps) for uid, fps in re.findall(r"uid:\s*(\d+)\s+frameRate:\s*([\d.]+)", section.group())}

    def restore(self) -> None:
        if self.guest is not None and self.guest == self.identify():
            try:
                self.display_limiter.restore()
            except (RuntimeError, subprocess.SubprocessError):
                pass
        self.display_limiter.clear()
        if self.applied and self.guest == self.identify():
            try:
                current = self.overrides()
                for uid, fps in self.original.items():
                    if math.isclose(current.get(uid, 0), self.applied.get(uid, -1), abs_tol=0.01):
                        self.override(uid, fps)
            except (RuntimeError, subprocess.SubprocessError):
                pass
        self.original.clear()
        self.applied.clear()
        self.package_uids.clear()

    def sync(self, fps: int | None, launch: tuple[int, str] | None, expected_guest: tuple[int, str] | None = None,
             *, force: bool = False, package: str | None = None, prepare: bool = False,
             active_packages: frozenset[str] = frozenset()) -> None:
        guest = self.identify() if launch else None
        if expected_guest and expected_guest != guest:
            guest = None
        if launch != self.launch or guest != self.guest:
            self.restore()
            self.launch = launch
            self.guest = guest
            self.sdk = None
            self.display_modes = None
        if guest is None or fps is None:
            return
        if self.sdk is None:
            output = self.android("getprop", "ro.build.version.sdk")
            sdk = next((line.strip() for line in output.splitlines() if line.strip().isdecimal()), "")
            if not sdk:
                return
            self.sdk = sdk
        if self.sdk != "33":
            raise RuntimeError(f"Android frame limiting has not been verified for SDK {self.sdk}")
        if self.display_modes is not True:
            supported = self.android("getprop", "waydroid.frame_limit_modes").strip() == "1"
            if supported and self.applied:
                self.restore()
            self.display_modes = supported
        if self.display_modes:
            target = self.display_limiter.sync(fps, force=force)
            if prepare:
                self.release_override(package)
            else:
                if package:
                    active_packages = active_packages | {package}
                self.sync_packages(target, active_packages)
            return
        if not fps:
            self.restore()
            return
        target = self.compatible_rate(fps)
        if target is None:
            return
        if prepare:
            self.release_override(package)
        else:
            foreground = package or self.foreground_package()
            uid = self.package_uid(foreground) if foreground else None
            uids = set(self.applied)
            if uid is not None:
                uids.add(uid)
            self.apply_uids(target, uids)

    def sync_packages(self, target: float, packages: frozenset[str]) -> None:
        for name in self.package_uids.keys() - packages:
            del self.package_uids[name]
        for name in packages - self.package_uids.keys():
            uid = self.package_uid(name)
            if uid is not None:
                self.package_uids[name] = uid
        uids = set(self.package_uids.values())
        for uid in self.applied.keys() - uids:
            self.release_uid(uid)
        self.apply_uids(target, uids)

    def release_override(self, package: str | None) -> None:
        if not package or not self.applied:
            return
        self.package_uids.pop(package, None)
        uid = self.package_uid(package)
        if uid in self.applied:
            self.release_uid(uid)

    def release_uid(self, uid: int) -> None:
        current = self.overrides().get(uid, 0)
        if math.isclose(current, self.applied[uid], abs_tol=0.01):
            self.override(uid, self.original[uid])
        del self.applied[uid]
        del self.original[uid]

    def apply_uids(self, target: float, uids: set[int]) -> None:
        changed = {uid for uid in uids if self.applied.get(uid) != target}
        if not changed:
            return
        current = self.overrides()
        for uid in changed:
            previous = current.get(uid, 0)
            if uid not in self.applied or not math.isclose(previous, self.applied[uid], abs_tol=0.01):
                self.original[uid] = previous
            self.override(uid, target)
            self.applied[uid] = target
