"""Collect the notices shipped with a native external-display payload."""

from pathlib import Path
import sys


def collect(source: Path, output: Path) -> None:
    notices = []
    for path in sorted((source / "hardware/waydroid/hwcomposer").rglob("*")):
        if path.suffix not in {".h", ".cpp"}:
            continue
        content = path.read_text(encoding="utf-8")
        if content.startswith("/*"):
            header = content[:content.index("*/") + 2]
            if header not in notices:
                notices.append(header)
    for name in (
        "hardware/interfaces/NOTICE", "external/wayland/COPYING",
        "external/wayland-protocols/freedesktop.org/COPYING",
        "external/wayland-protocols/ISC_LICENSE.txt", "external/libffi/LICENSE",
        "external/libxkbcommon/LICENSE",
    ):
        notices.append(name + "\n\n" + (source / name).read_text(encoding="utf-8"))
    output.write_text("\n\n".join(notices) + "\n", encoding="utf-8")


if __name__ == "__main__":
    collect(Path(sys.argv[1]), Path(sys.argv[2]))
