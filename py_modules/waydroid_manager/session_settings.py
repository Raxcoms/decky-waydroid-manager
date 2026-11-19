"""Build launch configuration without changing installed Waydroid files."""

from pathlib import Path
import re


EXTERNAL_PROPERTY = "waydroid.wayland_display_ext"
EXTERNAL_SOCKET = "wayland-1"


def external_mount(socket: Path) -> bytes:
    value = socket.as_posix()
    if any(character.isspace() for character in value) or "\\" in value or "\x00" in value:
        raise RuntimeError("Waydroid external display socket has an invalid path")
    return f"lxc.mount.entry = {value} run/xdg/{EXTERNAL_SOCKET} none rbind,create=file 0 0\n".encode()


def external_settings(content: bytes) -> bytes:
    text = content.decode("utf-8")
    if re.search(rf"(?m)^\s*{re.escape(EXTERNAL_PROPERTY)}\s*=", text):
        raise RuntimeError("Waydroid external display property is already configured")
    entry = f"{EXTERNAL_PROPERTY}={EXTERNAL_SOCKET}\n"
    lines = text.splitlines(keepends=True)
    section = next((index for index, line in enumerate(lines)
                    if re.fullmatch(r"\s*\[properties\]\s*(?:\r?\n)?", line)), None)
    if section is None:
        if text and not text.endswith("\n"):
            text += "\n"
        return (text + "[properties]\n" + entry).encode()
    end = next((index for index in range(section + 1, len(lines))
                if re.fullmatch(r"\s*\[[^]]+\]\s*(?:\r?\n)?", lines[index])), len(lines))
    if end and not lines[end - 1].endswith("\n"):
        lines[end - 1] += "\n"
    lines.insert(end, entry)
    return "".join(lines).encode()


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Waydroid configuration is not a regular file: {path}")
    return path.read_bytes()


def session_configuration(config_dir: Path, external: Path | None) -> dict[Path, bytes]:
    base_path = config_dir / "waydroid_base.prop"
    base = _read(base_path)
    if re.search(rb"(?m)^\s*waydroid\.wayland_display_ext\s*=", base):
        raise RuntimeError("Waydroid's external display property is already configured")
    if external is None:
        return {}
    config = config_dir / "lxc/waydroid/config"
    settings = config_dir / "waydroid.cfg"
    return {
        config: _read(config).rstrip(b"\n") + b"\n" + external_mount(external),
        settings: external_settings(_read(settings)),
        base_path: base.rstrip(b"\n") + f"\n{EXTERNAL_PROPERTY}={EXTERNAL_SOCKET}\n".encode()
            + b"waydroid.external_display_active=0\nwaydroid.external_display_visible=0\n",
    }
