from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


FRAGMENT = "waydroid-manager-second-screen.conf"


class LegacySessionRecovery:
    """Restore configuration left by the retired session-file writer."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.lxc = config_dir / "lxc/waydroid"
        self.config = self.lxc / "config"
        self.settings = config_dir / "waydroid.cfg"
        self.base_properties = config_dir / "waydroid_base.prop"
        self.fragment = self.lxc / FRAGMENT
        self.root = config_dir / "waydroid-manager-session"
        self.manifest = self.root / "manifest.json"
        self.backups = self.root / "backups"

    @staticmethod
    def _digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _read(self, path: Path, *, required: bool = True) -> bytes | None:
        try:
            if path.is_symlink():
                raise RuntimeError(f"Waydroid session file is not regular: {path}")
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
                or state.get("phase") not in {"staging", "active"}
                or not isinstance(state.get("entries"), list)):
            raise RuntimeError("Waydroid session manifest is invalid")
        expected = {"config": self.config, "settings": self.settings, "fragment": self.fragment,
                    "baseProperties": self.base_properties}
        seen = set()
        for entry in state["entries"]:
            if not isinstance(entry, dict):
                raise RuntimeError("Waydroid session manifest is invalid")
            name = entry.get("name")
            if (not isinstance(name, str) or name not in expected or name in seen
                    or entry.get("path") != str(expected[name].relative_to(self.config_dir))
                    or type(entry.get("created")) is not bool
                    or type(entry.get("mode")) is not int or not 0 <= entry["mode"] <= 0o777
                    or not isinstance(entry.get("sourceDigest"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", entry["sourceDigest"])
                    or (not entry["created"] and (not isinstance(entry.get("originalDigest"), str)
                        or not re.fullmatch(r"[0-9a-f]{64}", entry["originalDigest"])))):
                raise RuntimeError("Waydroid session manifest is invalid")
            seen.add(name)
        if seen != set(expected):
            raise RuntimeError("Waydroid session manifest is invalid")
        return state

    def recover(self) -> bool:
        state = self._read_manifest()
        if state is None:
            return False
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
                elif current is None or self._digest(current) != entry.get("originalDigest"):
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
        if self.backups.exists():
            self.backups.rmdir()
        try:
            self.root.rmdir()
        except OSError:
            pass
        return True
