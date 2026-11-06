import os
import re
import subprocess


def launch_resolution(display: str) -> tuple[int, int] | None:
    if not display:
        return None
    try:
        result = subprocess.run(
            ["xrandr", "--current"], env={**os.environ, "DISPLAY": display},
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    match = re.search(r"\bcurrent\s+(\d+)\s+x\s+(\d+)\b", result.stdout)
    if not match:
        return None
    width, height = map(int, match.groups())
    return (width, height) if 1 < width <= 32767 and 1 < height <= 32767 else None
