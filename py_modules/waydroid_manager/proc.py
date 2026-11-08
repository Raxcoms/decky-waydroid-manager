import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SteamSession:
    socket: Path
    data_home: Path | None


def steam_session(uid: int, proc: Path = Path("/proc"), runtime: Path | None = None) -> SteamSession | None:
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
            data_home = Path(os.fsdecode(environment.get(b"XDG_DATA_HOME", b"")))
            for key in (b"GAMESCOPE_WAYLAND_DISPLAY", b"WAYLAND_DISPLAY"):
                value = environment.get(key)
                if value:
                    socket = directory / os.fsdecode(value)
                    if socket.is_socket():
                        session = SteamSession(socket.resolve(), data_home if data_home.is_absolute() else None)
                        candidates.append(((key == b"GAMESCOPE_WAYLAND_DISPLAY", b"steam" in names), session))
                        break
        except OSError:
            continue
    if not candidates:
        return None
    best_rank = max(rank for rank, _ in candidates)
    sessions = {session for rank, session in candidates if rank == best_rank}
    return sessions.pop() if len(sessions) == 1 else None


def steam_wayland_socket(uid: int, proc: Path = Path("/proc"), runtime: Path | None = None) -> Path | None:
    session = steam_session(uid, proc, runtime)
    return session.socket if session else None


def process_identity(pid: int) -> tuple[int, str] | None:
    try:
        fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return (pid, fields[19]) if fields[0] != "Z" else None
    except (OSError, IndexError):
        return None


def descends_from(pid: int, owner: tuple[int, str]) -> bool:
    while pid > 1:
        if pid == owner[0]:
            return process_identity(pid) == owner
        try:
            fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
            pid = int(fields[1])
        except (OSError, ValueError, IndexError):
            return False
    return False


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
