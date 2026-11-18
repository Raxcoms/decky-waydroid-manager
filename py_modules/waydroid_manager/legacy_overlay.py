import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


class LegacyOverlayRecovery:
    """Restore files left by the retired on-disk overlay writer."""

    def __init__(self, config_dir: Path):
        self.overlay = config_dir / "overlay"
        self.root = config_dir / "waydroid-manager-overlay"
        self.manifest = self.root / "manifest.json"
        self.backups = self.root / "backups"

    @staticmethod
    def _relative(value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise RuntimeError("Invalid Waydroid overlay path")
        return path

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _target(self, relative: str | Path) -> Path:
        return self.overlay / self._relative(relative)

    def _read_manifest(self) -> dict | None:
        try:
            if self.manifest.stat().st_size > 1024 * 1024:
                raise RuntimeError("Waydroid overlay manifest is too large")
            value = json.loads(self.manifest.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise RuntimeError("Waydroid overlay manifest is invalid") from error
        if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("entries"), list):
            raise RuntimeError("Waydroid overlay manifest is invalid")
        return value

    @staticmethod
    def _copy(source: Path, target: Path, mode: int | None = None) -> None:
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as file:
            temporary = Path(file.name)
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, file)
            file.flush()
            os.fsync(file.fileno())
        if mode is not None:
            temporary.chmod(mode)
        temporary.replace(target)

    def recover(self) -> bool:
        state = self._read_manifest()
        if state is None:
            return False
        errors = []
        for entry in reversed(state["entries"]):
            try:
                relative = self._relative(entry.get("path", ""))
                target = self._target(relative)
                backup = self.backups / relative
                if entry.get("created") is True:
                    if target.exists() or target.is_symlink():
                        if not target.is_file() or target.is_symlink():
                            raise RuntimeError(f"Waydroid overlay target changed: {target}")
                        if self._digest(target) != entry.get("sourceDigest"):
                            raise RuntimeError(f"Waydroid overlay target changed: {target}")
                        target.unlink()
                elif backup.is_file() and not backup.is_symlink():
                    if not target.is_file() or target.is_symlink():
                        raise RuntimeError(f"Waydroid overlay target changed: {target}")
                    current = self._digest(target)
                    if current == entry.get("sourceDigest"):
                        self._copy(backup, target, backup.stat().st_mode & 0o777)
                    elif current != self._digest(backup):
                        raise RuntimeError(f"Waydroid overlay target changed: {target}")
                else:
                    raise RuntimeError(f"Waydroid overlay backup is missing: {backup}")
            except (OSError, RuntimeError) as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("Could not restore the Waydroid overlay: " + "; ".join(errors))
        if self.backups.exists():
            shutil.rmtree(self.backups)
        self.manifest.unlink(missing_ok=True)
        try:
            self.root.rmdir()
        except OSError:
            pass
        return True
