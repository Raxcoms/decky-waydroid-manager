from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


PROPERTY = "waydroid.wayland_display_ext"
FRAGMENT = "waydroid-manager-second-screen.conf"
INCLUDE_MARKER = "# Waydroid Manager second screen"


class SessionConfigLease:
    """Temporarily extend Waydroid's generated session configuration."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.lxc = config_dir / "lxc/waydroid"
        self.config = self.lxc / "config"
        self.settings = config_dir / "waydroid.cfg"
        self.fragment = self.lxc / FRAGMENT
        self.root = config_dir / "waydroid-manager-session"
        self.manifest = self.root / "manifest.json"
        self.backups = self.root / "backups"

    @staticmethod
    def _digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _read(self, path: Path, *, required: bool = True) -> bytes | None:
        try:
            if not path.exists():
                if required:
                    raise RuntimeError(f"Waydroid session file is missing: {path}")
                return None
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"Waydroid session file is not regular: {path}")
            return path.read_bytes()
        except FileNotFoundError:
            raise RuntimeError(f"Waydroid session file is missing: {path}") from None

    @staticmethod
    def _write(path: Path, content: bytes, mode: int = 0o644) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(mode)
        temporary.replace(path)

    def _write_manifest(self, state: dict) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._write(self.manifest, json.dumps(state, sort_keys=True).encode() + b"\n", 0o600)

    def _read_manifest(self) -> dict | None:
        try:
            if self.manifest.stat().st_size > 1024 * 1024:
                raise RuntimeError("Waydroid session manifest is too large")
            state = json.loads(self.manifest.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise RuntimeError("Waydroid session manifest is invalid") from error
        if (not isinstance(state, dict) or state.get("version") != 1
                or not isinstance(state.get("entries"), list)):
            raise RuntimeError("Waydroid session manifest is invalid")
        return state

    def _entry(self, name: str, path: Path, content: bytes) -> dict:
        original = self._read(path, required=False)
        return {
            "name": name,
            "path": str(path.relative_to(self.config_dir)),
            "created": original is None,
            "sourceDigest": self._digest(content),
            "originalDigest": self._digest(original) if original is not None else None,
            "mode": path.stat().st_mode & 0o777 if original is not None else 0o644,
        }

    @staticmethod
    def _include_config(content: bytes, fragment: Path) -> bytes:
        include = f"{INCLUDE_MARKER}\nlxc.include = {fragment}\n".encode()
        if include in content:
            raise RuntimeError("Waydroid second-screen include is already configured")
        if not content.endswith(b"\n"):
            content += b"\n"
        return content + include

    @staticmethod
    def _property_config(content: bytes) -> bytes:
        text = content.decode("utf-8")
        if re.search(rf"(?m)^\s*{re.escape(PROPERTY)}\s*=", text):
            raise RuntimeError("Waydroid external display property is already configured")
        lines = text.splitlines(keepends=True)
        section = next((index for index, line in enumerate(lines)
                        if re.fullmatch(r"\s*\[properties\]\s*(?:\r?\n)?", line)), None)
        if section is None:
            if text and not text.endswith("\n"):
                text += "\n"
            return (text + f"[properties]\n{PROPERTY}=wayland-1\n").encode()
        end = next((index for index in range(section + 1, len(lines))
                    if re.fullmatch(r"\s*\[[^]]+\]\s*(?:\r?\n)?", lines[index])), len(lines))
        lines.insert(end, f"{PROPERTY}=wayland-1\n")
        return "".join(lines).encode()

    @staticmethod
    def _fragment_config(socket: Path) -> bytes:
        value = socket.as_posix()
        if any(character.isspace() for character in value) or "\n" in value or "\r" in value:
            raise RuntimeError("Waydroid external display socket has an invalid path")
        return f"lxc.mount.entry = {value} run/xdg/wayland-1 none rbind,create=file 0 0\n".encode()

    def acquire(self, socket: Path) -> None:
        if self._read_manifest() is not None:
            raise RuntimeError("Waydroid session lease is already active")
        config = self._read(self.config)
        settings = self._read(self.settings)
        fragment = self._fragment_config(socket)
        contents = {
            "config": self._include_config(config, self.fragment),
            "settings": self._property_config(settings),
            "fragment": fragment,
        }
        paths = {"config": self.config, "settings": self.settings, "fragment": self.fragment}
        entries = [self._entry(name, paths[name], content) for name, content in contents.items()]
        self._write_manifest({"version": 1, "phase": "staging", "entries": entries})
        try:
            for entry in entries:
                path = self.config_dir / entry["path"]
                original = self._read(path, required=False)
                if original is not None:
                    self._write(self.backups / entry["path"], original, entry["mode"])
                self._write(path, contents[entry["name"]], entry["mode"])
            self._write_manifest({"version": 1, "phase": "active", "entries": entries})
        except Exception:
            self.recover()
            raise

    def recover(self) -> bool:
        state = self._read_manifest()
        if state is None:
            return False
        staging = state.get("phase") == "staging"
        errors = []
        for entry in reversed(state["entries"]):
            try:
                path = self.config_dir / entry["path"]
                current = self._read(path, required=False)
                if entry.get("created") is True:
                    if current is not None:
                        if self._digest(current) != entry.get("sourceDigest"):
                            raise RuntimeError(f"Waydroid session file changed: {path}")
                        path.unlink()
                elif current is not None and self._digest(current) == entry.get("sourceDigest"):
                    backup = self._read(self.backups / entry["path"])
                    if self._digest(backup) != entry.get("originalDigest"):
                        raise RuntimeError(f"Waydroid session backup changed: {path}")
                    self._write(path, backup, entry["mode"])
                elif not staging or current is None or self._digest(current) != entry.get("originalDigest"):
                    raise RuntimeError(f"Waydroid session file changed: {path}")
            except (OSError, RuntimeError) as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("Could not restore the Waydroid session configuration: " + "; ".join(errors))
        for path in sorted(self.backups.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        self.manifest.unlink(missing_ok=True)
        try:
            self.root.rmdir()
        except OSError:
            pass
        return True
