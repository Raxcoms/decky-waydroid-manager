"""Merge Android's resolution-to-density policy using the system Python."""

import sys
import xml.etree.ElementTree as ET


def density_settings(source: bytes, width: int, height: int, dpi: int) -> bytes:
    if min(width, height, dpi) <= 0:
        raise ValueError("Invalid display density reference")
    root = ET.fromstring(source) if source else ET.Element("displayConfiguration")
    if root.tag.rsplit("}", 1)[-1] != "displayConfiguration":
        raise ValueError("Invalid Android display configuration")
    namespace = root.tag[:-len("displayConfiguration")]
    if root.find(namespace + "densityMapping") is not None:
        return source
    mapping = ET.Element(namespace + "densityMapping")
    root.insert(0, mapping)
    entry = ET.SubElement(mapping, namespace + "density")
    for name, value in (("width", width), ("height", height), ("density", dpi)):
        ET.SubElement(entry, namespace + name).text = str(value)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    sys.stdout.buffer.write(density_settings(sys.stdin.buffer.read(1024 * 1024), *map(int, sys.argv[1:])))
