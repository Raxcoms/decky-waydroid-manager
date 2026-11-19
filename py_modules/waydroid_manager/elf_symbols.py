"""Read defined dynamic symbols without requiring a host binutils installation."""

from pathlib import Path
import struct


def dynamic_symbols(path: Path) -> dict[str, int]:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise RuntimeError("Android runtime library is too large")
    data = path.read_bytes()
    try:
        if data[:6] != b"\x7fELF\x02\x01":
            raise ValueError("Unsupported runtime ELF format")
        offset = struct.unpack_from("<Q", data, 40)[0]
        size, count = struct.unpack_from("<HH", data, 58)
        if size != 64 or not count or offset + size * count > len(data):
            raise ValueError("Invalid ELF section table")
        sections = [struct.unpack_from("<IIQQQQIIQQ", data, offset + index * size) for index in range(count)]
        result = {}
        for section in sections:
            if section[1] != 11:
                continue
            strings = sections[section[6]]
            names = data[strings[4]:strings[4] + strings[5]]
            if section[9] != 24 or section[4] + section[5] > len(data) or len(names) != strings[5]:
                raise ValueError("Invalid ELF dynamic symbols")
            for position in range(section[4], section[4] + section[5], 24):
                name, info, _, defined, _, length = struct.unpack_from("<IBBHQQ", data, position)
                if defined and info >> 4 in (1, 2):
                    end = names.index(b"\0", name)
                    result[names[name:end].decode("ascii")] = length
        return result
    except (ValueError, IndexError, struct.error, UnicodeError) as error:
        raise RuntimeError("Invalid Android runtime ELF symbols") from error
