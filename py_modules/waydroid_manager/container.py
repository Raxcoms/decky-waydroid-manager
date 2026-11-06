from pathlib import Path
import subprocess

from .proc import clean_env


CONFIG_DIR = Path("/var/lib/waydroid")
LXC_PATH = CONFIG_DIR / "lxc"
SERVICE = "waydroid-container.service"


def container_pid() -> int | None:
    try:
        result = subprocess.run(
            ["lxc-info", "-P", str(LXC_PATH), "-n", "waydroid", "-pH"],
            env=clean_env(), capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return int(value) if result.returncode == 0 and value.isdecimal() and int(value) > 0 else None
