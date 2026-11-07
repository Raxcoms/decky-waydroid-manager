import struct


def encode(items):
    output = bytearray()
    for key, (value_type, value) in items.items():
        output.append(value_type)
        output.extend(key.encode("utf-8"))
        output.append(0)
        if value_type == 0:
            output.extend(encode(value))
        elif value_type == 1:
            output.extend(str(value).encode("utf-8"))
            output.append(0)
        elif value_type == 2:
            output.extend(struct.pack("<i", value))
        elif value_type == 7:
            output.extend(struct.pack("<Q", value))
        else:
            raise RuntimeError(f"Unsupported Steam shortcut field type {value_type}")
    output.append(8)
    return bytes(output)



def write_shortcuts(path, entries):
    path.write_bytes(encode({"shortcuts": (0, entries)}))
