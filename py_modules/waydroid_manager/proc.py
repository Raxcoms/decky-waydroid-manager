import os
from pathlib import Path


def active_launch(uid: int, relay: Path) -> tuple[int, str] | None:
    for process in Path("/proc").glob("[0-9]*"):
        try:
            if process.stat().st_uid != uid:
                continue
            args = (process / "cmdline").read_bytes().split(b"\0")
            if len(args) < 2 or os.fsdecode(args[1]) != str(relay):
                continue
            return int(process.name), (process / "stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, ValueError, IndexError):
            continue
    return None


def clean_env():
    # Keep Decky's bundled libraries out of system commands.
    environment = dict(os.environ)
    original = environment.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        environment["LD_LIBRARY_PATH"] = original
    else:
        environment.pop("LD_LIBRARY_PATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    return environment
