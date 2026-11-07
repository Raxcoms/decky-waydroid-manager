from collections import deque
from pathlib import Path
import re
import subprocess
import threading
from typing import Callable

from .proc import clean_env


DOWNLOAD = re.compile(r"\[Downloading\]\s+([\d.]+)\s+MB/\s*([\d.]+)\s+MB")
ImageProgress = Callable[[str, int | None], None]


def require_unredirected(path: Path) -> None:
    if path.resolve() != path:
        raise RuntimeError(f"Waydroid path is redirected: {path}")


def require_unmounted(paths: tuple[Path, ...], mountinfo: Path = Path("/proc/self/mountinfo")) -> None:
    for line in mountinfo.read_text().splitlines():
        mountpoint = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), line.split()[4])
        if any(Path(mountpoint).is_relative_to(path) for path in paths):
            raise RuntimeError(f"Waydroid data is still mounted at {mountpoint}")


def launcher_packages(output: str) -> set[str]:
    packages = set()
    package = ""
    for line in output.splitlines():
        if line.startswith("Name:"):
            package = ""
        elif line.startswith("packageName: "):
            package = line.removeprefix("packageName: ").strip()
        elif line.strip() == "android.intent.category.LAUNCHER" and package:
            packages.add(package)
    return packages


def run_init(command: list[str], report: ImageProgress, timeout: int = 1800) -> str:
    output: deque[str] = deque(maxlen=20)
    env = {**clean_env(), "PYTHONUNBUFFERED": "1"}
    with subprocess.Popen(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace",
    ) as process:
        def read_output():
            for line in process.stdout:
                match = DOWNLOAD.search(line)
                if match:
                    try:
                        current, total = map(float, match.groups())
                        if total > 0:
                            report("downloading", min(100, int(current / total * 100)))
                    except (ValueError, OverflowError):
                        pass
                line = line.strip()
                if line and not line.startswith("[Downloading]"):
                    output.append(line)
                if "] Downloading " in line:
                    report("downloading", None)
                elif "] Validating " in line or "] Extracting " in line:
                    report("finalizing", None)

        reader = threading.Thread(target=read_output)
        reader.start()
        try:
            process.wait(timeout=timeout)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            reader.join()

    result = "\n".join(output)
    if process.returncode:
        raise RuntimeError(result or "Waydroid image initialization failed")
    return result
