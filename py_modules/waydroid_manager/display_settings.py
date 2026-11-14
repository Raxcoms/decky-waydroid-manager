"""Merge temporary display defaults using the host Python's XML support."""

from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def merge(path: Path) -> bytes:
    root = ET.fromstring(path.read_bytes())
    if root.tag != "displays":
        raise RuntimeError("Waydroid display settings are invalid")
    config = root.find("config")
    name = "port:1" if config is not None and config.get("identifier") == "1" else "local:1"
    entry = next((display for display in root.findall("display") if display.get("name") == name), None)
    if entry is None:
        entry = ET.SubElement(root, "display", {"name": name})
    entry.set("shouldShowSystemDecors", "true")
    entry.set("imePolicy", "0")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    sys.stdout.buffer.write(merge(Path(sys.argv[1])))
