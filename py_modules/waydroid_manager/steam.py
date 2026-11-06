from pathlib import Path
import re
import shlex
import struct


MAX_SHORTCUT_BYTES = 16 * 1024 * 1024


def read_shortcuts(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.stat().st_size > MAX_SHORTCUT_BYTES:
        raise RuntimeError("Steam shortcuts.vdf is too large")
    data = path.read_bytes()

    def text(offset):
        end = data.index(b"\0", offset)
        return data[offset:end].decode("utf-8", errors="replace"), end + 1

    def object_at(offset, depth=0):
        if depth > 8:
            raise ValueError("Too many nested objects")
        result = {}
        while offset < len(data):
            kind = data[offset]
            offset += 1
            if kind == 8:
                return result, offset
            key, offset = text(offset)
            if kind == 0:
                value, offset = object_at(offset, depth + 1)
            elif kind == 1:
                value, offset = text(offset)
            elif kind in {2, 3, 7, 10}:
                fmt = {2: "<i", 3: "<f", 7: "<Q", 10: "<q"}[kind]
                value = struct.unpack_from(fmt, data, offset)[0]
                offset += struct.calcsize(fmt)
            else:
                raise ValueError(f"Unsupported field type {kind}")
            result[key] = (kind, value)
        raise ValueError("Missing object terminator")

    try:
        root, _ = object_at(0)
        kind, shortcuts = root["shortcuts"]
        if kind != 0:
            raise ValueError("Invalid shortcut root")
        return shortcuts
    except (KeyError, ValueError, struct.error) as error:
        raise RuntimeError("Steam shortcuts.vdf is malformed") from error


def shortcut_key(options: str) -> str | None:
    try:
        args = shlex.split(options)
    except ValueError:
        return None
    if args and args[-1] == "full":
        return "waydroid"
    if len(args) >= 2 and args[-2] == "app" and re.fullmatch(r"[A-Za-z0-9._-]+", args[-1]):
        return args[-1]
    return None


def shortcuts_path(home: Path) -> Path:
    roots = (home / ".local/share/Steam", home / ".steam/steam", home / ".var/app/com.valvesoftware.Steam/data/Steam")
    for root in roots:
        accounts = {path.name: path / "config/shortcuts.vdf" for path in (root / "userdata").glob("*") if path.name.isdecimal() and path.is_dir()}
        if not accounts:
            continue
        login = root / "config/loginusers.vdf"
        if login.is_file():
            users = read_login_users(login)
            recent = [steam_id for steam_id, body in users.items() if body.get("MostRecent") == "1"]
            if len(recent) == 1:
                account = str(int(recent[0]) & 0xFFFFFFFF)
                if account in accounts:
                    return accounts[account]
                raise RuntimeError("The active Steam account has no userdata directory")
        if len(accounts) == 1:
            return next(iter(accounts.values()))
        raise RuntimeError("Could not identify the active Steam account")
    raise RuntimeError("Steam has no userdata directory for this user yet")


def read_login_users(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    tokens = [("text", re.sub(r'\\(["\\])', r'\1', match[1])) if match[1] is not None else (match[2], match[2])
              for match in re.finditer(r'"((?:\\.|[^"\\])*)"|([{}])|//[^\n]*', text) if match[1] is not None or match[2]]
    offset = 0

    def object_at(depth=0):
        nonlocal offset
        if depth > 4:
            raise RuntimeError("Steam loginusers.vdf is malformed")
        result = {}
        while offset < len(tokens):
            kind, key = tokens[offset]
            offset += 1
            if kind == "}":
                return result
            if kind != "text" or offset >= len(tokens):
                raise RuntimeError("Steam loginusers.vdf is malformed")
            kind, value = tokens[offset]
            offset += 1
            result[key] = object_at(depth + 1) if kind == "{" else value
        return result

    users = object_at().get("users", {})
    return {key: value for key, value in users.items() if key.isdecimal() and isinstance(value, dict)} if isinstance(users, dict) else {}
