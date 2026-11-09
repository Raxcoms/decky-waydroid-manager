from pathlib import Path
import subprocess

from .proc import clean_env, process_identity


CONFIG_DIR = Path("/var/lib/waydroid")
LXC_PATH = CONFIG_DIR / "lxc"
SERVICE = "waydroid-container.service"


def vendor_overlay_warning(config_dir: Path = CONFIG_DIR, mountinfo: Path = Path("/proc/self/mountinfo")) -> str | None:
    staged = config_dir / "overlay/vendor"
    target = config_dir / "rootfs/vendor"
    try:
        if not any(path.is_file() for path in staged.glob("lib*/**/*.so")):
            return None
        mounts = []
        for line in mountinfo.read_text(errors="replace").splitlines():
            fields, _, filesystem = line.partition(" - ")
            if len(parts := fields.split()) > 4 and parts[4] == str(target):
                mounts.append(filesystem.split())
    except OSError:
        return None
    if not mounts:
        return None
    for filesystem in mounts:
        if len(filesystem) < 3 or filesystem[0] != "overlay":
            continue
        for option in filesystem[2].split(","):
            if option.startswith("lowerdir=") and str(staged) in option.removeprefix("lowerdir=").split(":"):
                return None
    return "Waydroid has staged vendor libraries, but its vendor overlay is not mounted. Check the host's Waydroid service and overlay configuration."


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


def container_identity() -> tuple[int, str] | None:
    pid = container_pid()
    return process_identity(pid) if pid else None


def session_uses_socket(display: Path) -> bool:
    try:
        result = subprocess.run(["waydroid", "status"], env=clean_env(), capture_output=True,
                                text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and any(
        line.partition(":")[2].strip() == str(display)
        for line in result.stdout.splitlines() if line.startswith("Wayland display:")
    )


def registered_guest(display: Path) -> tuple[int, str] | None:
    identity = container_identity()
    if identity and session_uses_socket(display) and process_identity(identity[0]) == identity:
        return identity
    return None
