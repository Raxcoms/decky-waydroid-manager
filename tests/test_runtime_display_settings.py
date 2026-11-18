from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from waydroid_manager.runtime_display import RuntimeDisplayLease


class DisplaySettingsTests(unittest.TestCase):
    def test_staging_merges_effective_vendor_policy_without_changing_installed_files(self):
        image_policy = ('<displays><config identifier="1" />'
                        '<display name="port:0" forcedDensity="240" />'
                        '<display name="other" windowingMode="5" /></displays>')
        override_policy = '<displays><display name="local:0" forcedDensity="320" /></displays>'
        for policy in ("image", "override", "missing"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = root / "config"
                vendor = config / "overlay/vendor/etc"
                vendor.mkdir(parents=True)
                (config / "waydroid.cfg").write_text("[waydroid]\nimages_path=/images\n")
                (config / "waydroid_base.prop").write_text("ro.hardware.gralloc=gbm\n")
                existing = vendor / "display_settings.xml"
                if policy == "override":
                    existing.write_text(override_policy)
                source = root / "defaults.xml"
                source.write_text('<displays><display name="local:1" shouldShowSystemDecors="true" /></displays>')
                reads = []

                def run(command, **kwargs):
                    if command[0] == "debugfs":
                        reads.append(command[2])
                        if policy != "missing":
                            Path(command[2].split(" ", 2)[2]).write_text(image_policy)
                    return ""

                lease = RuntimeDisplayLease(config, root / "runtime")
                try:
                    with patch.object(lease, "start_guard"):
                        lease.acquire({"vendor/etc/display_settings.xml": source}, None, run, Path("socket"))
                    staged = ET.parse(lease.root / "overlay/vendor/etc/display_settings.xml").getroot()
                    entries = {entry.get("name"): entry.attrib for entry in staged.findall("display")}
                    if policy == "image":
                        self.assertEqual(entries["port:0"]["forcedDensity"], "240")
                        self.assertEqual(entries["other"]["windowingMode"], "5")
                        self.assertEqual(entries["port:1"]["shouldShowSystemDecors"], "true")
                    else:
                        self.assertEqual(entries["local:1"]["shouldShowSystemDecors"], "true")
                    if policy == "override":
                        self.assertEqual(existing.read_text(), override_policy)
                        self.assertEqual(entries["local:0"]["forcedDensity"], "320")
                        self.assertEqual(reads, [])
                    else:
                        self.assertFalse(existing.exists())
                        self.assertEqual(len(reads), 1)
                finally:
                    lease.recover()

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
