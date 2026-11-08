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
        return {"accounts": {}, "removableApps": [], "artwork": {}}

    @staticmethod
    def shortcut_defaults() -> dict:
        return {"autoAddApps": False, "observedApps": [], "pendingApps": [], "shortcuts": {},
                "removedShortcuts": [], "pendingRemovals": {}}

    @staticmethod
    def account(state: dict, account_id: int) -> dict:
        return state["accounts"].setdefault(str(account_id), StateStore.shortcut_defaults())

    @staticmethod
    def _strings(values) -> list[str]:
        return sorted({value for value in values if isinstance(value, str)}) if isinstance(values, list) else []

    @staticmethod
    def _valid_id_key(key: str) -> bool:
        return 0 < len(key) <= 10 and key.isascii() and key.isdecimal() and 0 < int(key) <= 0xFFFFFFFF and str(int(key)) == key

    @staticmethod
    def _shortcut_state(saved: dict) -> dict:
        state = StateStore.shortcut_defaults()
        state["autoAddApps"] = saved.get("autoAddApps") is True
        for key in ("observedApps", "pendingApps", "removedShortcuts"):
            state[key] = StateStore._strings(saved.get(key))
        if isinstance(saved.get("shortcuts"), dict):
            state["shortcuts"] = {key: value for key, value in saved["shortcuts"].items()
                                  if isinstance(key, str) and type(value) is int and 0 < value <= 0xFFFFFFFF}
        if isinstance(saved.get("pendingRemovals"), dict):
            state["pendingRemovals"] = {key: value for key, value in saved["pendingRemovals"].items()
                                        if StateStore._valid_id_key(key) and isinstance(value, str)}
        return state

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
        state["removableApps"] = self._strings(saved.get("removableApps"))
        accounts = saved.get("accounts")
        if isinstance(accounts, dict):
            state["accounts"] = {key: self._shortcut_state(value) for key, value in accounts.items()
                                 if self._valid_id_key(key) and isinstance(value, dict)}
        legacy = saved.get("legacy", saved if accounts is None else {})
        if isinstance(legacy, dict):
            history = self._shortcut_state(legacy)
            if history != self.shortcut_defaults():
                state["legacy"] = history
        if isinstance(saved.get("artwork"), dict):
            state["artwork"] = {key: value for key, value in saved["artwork"].items()
                                if isinstance(key, str) and isinstance(value, str) and ARTWORK_RECORD.fullmatch(value)}
        return state

    def save(self, state: dict) -> None:
        self._validate_path()
        state = {**state, "accounts": {key: history for key, history in state["accounts"].items()
                                       if history != self.shortcut_defaults()}}
        if state == self.defaults():
            self.clear()
            return
        if self.load() == state:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(state, temporary, sort_keys=True)
                temporary.flush()
                os.fsync(temporary.fileno())
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
