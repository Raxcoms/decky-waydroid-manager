"""Select temporary composer modes without changing Android's saved settings."""

from dataclasses import dataclass
import re
import time


@dataclass(frozen=True)
class DisplayModes:
    display: int
    active: int
    rates: dict[int, float]

    @classmethod
    def primary(cls, output: str) -> "DisplayModes":
        section = re.search(r"^Display (\d+) \(internal, primary,[^\n]*\n(.*?)(?=^Display |\Z)",
                            output, re.MULTILINE | re.DOTALL)
        if not section:
            raise RuntimeError("Android did not report its primary display modes")
        active = re.search(r"\bactiveModeId=(\d+)", section[2])
        rates = {int(mode): float(rate) for mode, rate in
                 re.findall(r"\{id=(\d+), hwcId=\d+, resolution=\d+x\d+, refreshRate=([\d.]+) Hz", section[2])}
        if not active or int(active[1]) not in rates or not rates or any(rate <= 0 for rate in rates.values()):
            raise RuntimeError("Android reported invalid primary display modes")
        return cls(int(section[1]), int(active[1]), rates)

    def select(self, fps: int) -> int:
        ceiling = min(float(fps), max(self.rates.values())) if fps else max(self.rates.values())
        candidates = [(rate, -mode, mode) for mode, rate in self.rates.items() if rate <= ceiling + 0.01]
        if not candidates:
            raise RuntimeError("The composer has no mode within the requested frame limit")
        return max(candidates)[2]


class DisplayFrameLimiter:
    POLICY_CHECK_INTERVAL = 30.0

    def __init__(self, android, clock=time.monotonic):
        self.android = android
        self.clock = clock
        self.next_check = 0.0
        self.original: tuple[int, int] | None = None
        self.applied: tuple[int, int] | None = None
        self.previous_limit: str | None = None
        self.limit: str | None = None

    def modes(self) -> DisplayModes:
        return DisplayModes.primary(self.android("dumpsys", "SurfaceFlinger"))

    def set_mode(self, display: int, mode: int) -> None:
        # Android 13 supports a temporary, per-display mode policy through this call.
        result = self.android("service", "call", "SurfaceFlinger", "1035", "i32", str(mode), "i64", str(display))
        if "Parcel(NULL)" not in result:
            raise RuntimeError("Android rejected the display frame limit")

    def sync(self, fps: int) -> None:
        value = str(fps)
        now = self.clock()
        if self.limit == value and self.applied is not None and now < self.next_check:
            return
        modes = self.modes()
        selected = modes.select(fps)
        if self.previous_limit is None:
            self.previous_limit = self.android("getprop", "waydroid.frame_limit").strip()
        if self.limit != value:
            self.android("setprop", "waydroid.frame_limit", value)
            self.limit = value
        if self.original is None:
            self.original = modes.display, modes.active
        target = modes.display, selected
        if self.applied != target or modes.active != selected:
            self.set_mode(*target)
            self.applied = target
        self.next_check = now + self.POLICY_CHECK_INTERVAL

    def restore(self) -> None:
        if self.limit is not None and self.android("getprop", "waydroid.frame_limit").strip() == self.limit:
            self.android("setprop", "waydroid.frame_limit", self.previous_limit or "0")
        if self.original and self.applied:
            modes = self.modes()
            if (modes.display, modes.active) == self.applied:
                self.set_mode(*self.original)
        self.clear()

    def clear(self) -> None:
        self.original = self.applied = None
        self.previous_limit = self.limit = None
        self.next_check = 0.0
