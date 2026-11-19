"""Reject generated Android and native build outputs in the tracked source tree."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def check() -> None:
    tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"]).decode().split("\0")
    generated = [name for name in tracked if Path(name).suffix.lower() in {".apk", ".dex", ".so", ".o", ".a"}]
    if generated:
        raise RuntimeError("Generated binaries must stay outside Git: " + ", ".join(generated))


if __name__ == "__main__":
    check()
