import os
from pathlib import Path


def steam_wayland_socket(uid: int, proc: Path = Path("/proc"), runtime: Path | None = None) -> Path | None:
    runtime = runtime if runtime is not None else Path(f"/run/user/{uid}")
    candidates = []
    for process in proc.glob("[0-9]*"):
        try:
            if process.stat().st_uid != uid:
                continue
            names = {arg.rsplit(b"/", 1)[-1] for arg in (process / "cmdline").read_bytes().split(b"\0")}
            if not names.intersection({b"steam", b"steamwebhelper"}):
                continue
            environment = dict(value.split(b"=", 1) for value in (process / "environ").read_bytes().split(b"\0") if b"=" in value)
            directory = Path(os.fsdecode(environment.get(b"XDG_RUNTIME_DIR", b"")))
            if not directory.is_absolute():
                directory = runtime
            for key in (b"GAMESCOPE_WAYLAND_DISPLAY", b"WAYLAND_DISPLAY"):
                value = environment.get(key)
                if value:
                    socket = directory / os.fsdecode(value)
                    if socket.is_socket():
                        candidates.append(((key == b"GAMESCOPE_WAYLAND_DISPLAY", b"steam" in names), socket.resolve()))
                        break
        except OSError:
            continue
    if not candidates:
        return None
    best_rank = max(rank for rank, _ in candidates)
    sockets = {path for rank, path in candidates if rank == best_rank}
    return sockets.pop() if len(sockets) == 1 else None


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
