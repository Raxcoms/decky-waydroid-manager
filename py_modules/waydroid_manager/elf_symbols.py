"""Read dynamic ELF symbols without requiring host binutils."""

from pathlib import Path
import struct


def _symbols(path: Path, *, undefined: bool) -> dict[str, int]:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise RuntimeError("Android runtime library is too large")
    data = path.read_bytes()
    try:
        if data[:4] != b"\x7fELF" or data[5] != 1:
            raise ValueError("Unsupported runtime ELF format")
        if data[4] == 1:
            offset = struct.unpack_from("<I", data, 32)[0]
            size, count = struct.unpack_from("<HH", data, 46)
            section_format, symbol_format, symbol_size = "<IIIIIIIIII", "<IIIBBH", 16
        elif data[4] == 2:
            offset = struct.unpack_from("<Q", data, 40)[0]
            size, count = struct.unpack_from("<HH", data, 58)
            section_format, symbol_format, symbol_size = "<IIQQQQIIQQ", "<IBBHQQ", 24
        else:
            raise ValueError("Unsupported runtime ELF class")
        if size != struct.calcsize(section_format) or not count or offset + size * count > len(data):
            raise ValueError("Invalid ELF section table")
        sections = [struct.unpack_from(section_format, data, offset + index * size) for index in range(count)]
        result = {}
        for section in sections:
            if section[1] != 11:
                continue
            strings = sections[section[6]]
            names = data[strings[4]:strings[4] + strings[5]]
            if (section[9] != symbol_size or section[4] + section[5] > len(data)
                    or len(names) != strings[5] or section[5] % symbol_size):
                raise ValueError("Invalid ELF dynamic symbols")
            for position in range(section[4], section[4] + section[5], symbol_size):
                entry = struct.unpack_from(symbol_format, data, position)
                if data[4] == 1:
                    name, _, length, info, _, defined = entry
                else:
                    name, info, _, defined, _, length = entry
                binding = info >> 4
                if not name or bool(defined) == undefined or binding not in ((1,) if undefined else (1, 2)):
                    continue
                end = names.index(b"\0", name)
                result[names[name:end].decode("ascii")] = length
        return result
    except (ValueError, IndexError, struct.error, UnicodeError) as error:
        raise RuntimeError("Invalid Android runtime ELF symbols") from error


def dynamic_symbols(path: Path) -> dict[str, int]:
    return _symbols(path, undefined=False)


def undefined_symbols(path: Path) -> frozenset[str]:
    return frozenset(_symbols(path, undefined=True))