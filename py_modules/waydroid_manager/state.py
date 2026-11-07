import json
import os
from errno import ENOTEMPTY
from pathlib import Path
import tempfile

from .artwork import ARTWORK_RECORD


class StateStore:
    def __init__(self, home: Path):
        self.home = home
        self.path = home / ".config/waydroid-manager/state.json"

    @staticmethod
    def defaults() -> dict:
        return {"autoAddApps": False, "observedApps": [], "pendingApps": [], "shortcuts": {},
                "removedShortcuts": [], "removableApps": [], "artwork": {}}

    def load(self) -> dict:
        self._validate_path()
        state = self.defaults()
        try:
            if self.path.stat().st_size > 4 * 1024 * 1024:
                return state
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return state
        if not isinstance(saved, dict):
            return state
        state["autoAddApps"] = saved.get("autoAddApps") is True
        for key in ("observedApps", "pendingApps", "removedShortcuts", "removableApps"):
            if isinstance(saved.get(key), list):
                state[key] = sorted({item for item in saved[key] if isinstance(item, str)})
        if isinstance(saved.get("shortcuts"), dict):
            state["shortcuts"] = {key: value for key, value in saved["shortcuts"].items()
                                  if isinstance(key, str) and type(value) is int and 0 < value <= 0xFFFFFFFF}
        if isinstance(saved.get("artwork"), dict):
            state["artwork"] = {key: value for key, value in saved["artwork"].items()
                                if isinstance(key, str) and isinstance(value, str) and ARTWORK_RECORD.fullmatch(value)}
        return state

    def save(self, state: dict) -> None:
        self._validate_path()
        if state == self.defaults():
            self.clear()
            return
        if self.load() == state:
            return
        owner = self.home.stat()
        missing = []
        directory = self.path.parent
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for directory in missing:
            os.chown(directory, owner.st_uid, owner.st_gid)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(state, temporary, sort_keys=True)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chown(temporary_path, owner.st_uid, owner.st_gid)
            temporary_path.replace(self.path)
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

    def clear(self) -> None:
        self._validate_path()
        self.path.unlink(missing_ok=True)
        try:
            self.path.parent.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            if error.errno != ENOTEMPTY:
                raise

    def _validate_path(self) -> None:
        if not self.path.resolve().is_relative_to(self.home.resolve()):
            raise RuntimeError("The plugin state directory is outside the user home")
