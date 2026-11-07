import math
import re
import subprocess
from typing import Callable


class FrameLimiter:
    def __init__(self, run: Callable[[list[str]], str]):
        self.run = run
        self.launch = None
        self.original: dict[int, float] = {}
        self.applied: dict[int, float] = {}
        self.sdk = None

    def android(self, *command: str) -> str:
        return self.run(["waydroid", "shell", "--", *command])

    def foreground_package(self) -> str | None:
        output = self.android("dumpsys", "activity", "activities")
        match = re.search(r"(?:topResumedActivity|mResumedActivity|ResumedActivity)\s*[:=]\s*.*?\bu\d+\s+([A-Za-z0-9._]+)/", output)
        return match.group(1) if match else None

    def package_uid(self, package: str) -> int | None:
        output = self.android("cmd", "package", "list", "packages", "-U", package)
        match = re.search(rf"^package:{re.escape(package)}\s+uid:(\d+)$", output, re.MULTILINE)
        return int(match.group(1)) if match else None

    def override(self, uid: int, fps: float) -> None:
        # Android 13's SurfaceFlinger exposes a temporary per-UID frame-rate override.
        self.android("service", "call", "SurfaceFlinger", "1039", "i32", str(uid), "f", str(fps))

    def compatible_rate(self, target: int) -> float | None:
        period, _, _ = self.android("dumpsys", "SurfaceFlinger", "--latency").partition("\n")
        period = period.strip()
        if not period.isdecimal() or not 1_000_000 <= int(period) <= 1_000_000_000:
            return None
        refresh = round(1_000_000_000 / int(period), 4)
        # Android needs a whole number of refresh periods. Steam rounds the displayed cap.
        divisor = max(1, math.ceil(refresh / (target + min(0.4999, target * 0.01))))
        return refresh / divisor

    def restore(self) -> None:
        for uid, fps in self.original.items():
            try:
                self.override(uid, fps)
            except (RuntimeError, subprocess.SubprocessError):
                pass
        self.original.clear()
        self.applied.clear()

    def sync(self, fps: int | None, launch: tuple[int, str] | None) -> None:
        if launch != self.launch:
            self.restore()
            self.launch = launch
            self.sdk = None
        if launch is None or fps is None:
            return
        if not fps:
            self.restore()
            return
        if self.sdk is None:
            output = self.android("getprop", "ro.build.version.sdk")
            sdk = next((line.strip() for line in output.splitlines() if line.strip().isdecimal()), "")
            if not sdk:
                return
            self.sdk = sdk
        if self.sdk != "33":
            raise RuntimeError(f"Android frame limiting has not been verified for SDK {self.sdk}")
        target = self.compatible_rate(fps)
        if target is None:
            return
        for uid, applied_fps in self.applied.items():
            if applied_fps != target:
                self.override(uid, target)
                self.applied[uid] = target
        package = self.foreground_package()
        if not package:
            return
        uid = self.package_uid(package)
        if uid is None or self.applied.get(uid) == target:
            return
        if uid not in self.original:
            output = self.android("dumpsys", "SurfaceFlinger")
            section = re.search(r"Frame Rate Overrides \(backdoor\):[^\n]*", output)
            if not section:
                raise RuntimeError("Could not read Android's existing frame-rate overrides")
            original = dict(re.findall(r"uid:\s*(\d+)\s+frameRate:\s*([\d.]+)", section.group()))
            self.original[uid] = float(original.get(str(uid), 0))
        self.override(uid, target)
        self.applied[uid] = target
