"""Optional host launch integration. Android features do not depend on Armada."""

import os
from pathlib import Path
import shlex
import shutil

from .apps import PACKAGE_RE


def launch_wrapper() -> Path | None:
    executable = shutil.which("armada-game-launch")
    if executable:
        return Path(executable)
    host_tool = shutil.which("systemd-run")
    if host_tool:
        # Armada publishes its wrapper in the host prefix's libexec directory.
        candidate = Path(host_tool).resolve().parent.parent / "libexec/armada/armada-game-launch"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def default_launch_options(action: str) -> str:
    wrapper = launch_wrapper()
    return f"{shlex.quote(str(wrapper))} %command% {action}" if wrapper else action


def updated_launch_options(current: str) -> str | None:
    try:
        args = shlex.split(current)
    except ValueError:
        return None
    canonical = args == ["full"] or (len(args) == 2 and args[0] == "app" and PACKAGE_RE.fullmatch(args[1]))
    if not canonical:
        return None
    updated = default_launch_options(" ".join(args))
    return updated if updated != current else None
