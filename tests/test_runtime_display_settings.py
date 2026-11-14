from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from waydroid_manager.runtime_display import RuntimeDisplayLease


class DisplaySettingsTests(unittest.TestCase):
    def test_preserves_existing_display_policy_and_port_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, existing = root / "source.xml", root / "existing.xml"
            source.write_text('<displays><display name="local:1" shouldShowSystemDecors="true" /></displays>')
            existing.write_text('<displays><config identifier="1" />'
                                '<display name="port:0" forcedDensity="200" />'
                                '<display name="port:1" userRotation="1" shouldShowSystemDecors="false" />'
                                '</displays>')
            before = existing.read_bytes()
            result = ET.fromstring(RuntimeDisplayLease._display_settings(source, existing))
            entries = {display.get("name"): display.attrib for display in result.findall("display")}
            self.assertEqual(entries["port:0"], {"name": "port:0", "forcedDensity": "200"})
            self.assertEqual(entries["port:1"], {"name": "port:1", "userRotation": "1", "shouldShowSystemDecors": "true", "imePolicy": "0"})
            self.assertEqual(existing.read_bytes(), before)

    def test_keeps_unrelated_unique_display_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, existing = root / "source.xml", root / "existing.xml"
            source.write_text('<displays><display name="local:1" shouldShowSystemDecors="true" /></displays>')
            existing.write_text('<displays><display name="external:other" windowingMode="5" /></displays>')
            result = ET.fromstring(RuntimeDisplayLease._display_settings(source, existing))
            entries = {display.get("name"): display.attrib for display in result.findall("display")}
            self.assertEqual(entries["external:other"]["windowingMode"], "5")
            self.assertEqual(entries["local:1"]["shouldShowSystemDecors"], "true")
