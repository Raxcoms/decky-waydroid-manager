import re
import subprocess
from typing import Callable


class FrameLimiter:
    def __init__(self, run: Callable[[list[str]], str]):
        self.run = run
        self.launch = None
        self.original: dict[int, float] = {}
        self.applied: dict[int, int] = {}
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

    def restore(self) -> None:
        for uid, fps in self.original.items():
            try:
                self.override(uid, fps)
            except (RuntimeError, subprocess.SubprocessError):
                pass
        self.original.clear()
        self.applied.clear()

    def sync(self, fps: int, launch: tuple[int, str] | None) -> None:
        if launch != self.launch:
            self.restore()
            self.launch = launch
            self.sdk = None
        if launch is None:
            return
        if not fps:
            self.restore()
            return
        for uid, applied_fps in list(self.applied.items()):
            if applied_fps != fps:
                self.override(uid, fps)
                self.applied[uid] = fps
        if self.sdk is None:
            output = self.android("getprop", "ro.build.version.sdk")
            sdk = next((line.strip() for line in output.splitlines() if line.strip().isdecimal()), "")
            if not sdk:
                return
            self.sdk = sdk
        if self.sdk != "33":
            raise RuntimeError(f"Android frame limiting has not been verified for SDK {self.sdk}")
        package = self.foreground_package()
        if not package:
            return
        uid = self.package_uid(package)
        if uid is None or self.applied.get(uid) == fps:
            return
        if uid not in self.original:
            output = self.android("dumpsys", "SurfaceFlinger")
            section = re.search(r"Frame Rate Overrides \(backdoor\):[^\n]*", output)
            if not section:
                raise RuntimeError("Could not read Android's existing frame-rate overrides")
            original = dict(re.findall(r"uid:\s*(\d+)\s+frameRate:\s*([\d.]+)", section.group()))
            self.original[uid] = float(original.get(str(uid), 0))
        self.override(uid, fps)
        self.applied[uid] = fps
