import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from waydroid_manager import display_resources as resources


class DisplayResourceTests(unittest.TestCase):
    def test_cache_is_image_specific_and_rebuilds_modified_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, plugin = root / "config", root / "plugin"
            config.mkdir()
            (config / "waydroid.cfg").write_text("[waydroid]\nimages_path=/images\n")
            source = plugin / "resources/display"
            source.mkdir(parents=True)
            for name in ("display_settings.xml", "wayland_tablet.idc"):
                (source / name).write_text("owned resource")
            tools = root / "tools"
            tools.mkdir()
            (tools / "manifest.json").write_text('{}')
            base = {"framework-res.apk": b"framework", "SystemUI.apk": b"system-ui"}
            identity = SimpleNamespace(framework_digest=hashlib.sha256(base["framework-res.apk"]).hexdigest(),
                                       system_ui_digest=hashlib.sha256(base["SystemUI.apk"]).hexdigest())
            builds = []
            def run(args, **kwargs):
                target = Path(args[2].split(" ", 2)[2])
                target.write_bytes(base[target.name])
                return "debugfs diagnostic"
            def build(args, **kwargs):
                output = Path(args[-1])
                builds.append(output)
                for name in resources.RESOURCE_FILES.values():
                    if name.endswith(".apk"):
                        (output / name).write_bytes(b"built against " + base["SystemUI.apk"])
            with patch.object(resources, "resource_tools", return_value=tools), patch.object(resources.subprocess, "run", side_effect=build):
                first = resources.prepare_payload(plugin, config, identity, run)
                self.assertEqual(first, resources.prepare_payload(plugin, config, identity, run))
                self.assertEqual(len(builds), 1)
                next(iter(first.values())).write_bytes(b"modified")
                resources.prepare_payload(plugin, config, identity, run)
                self.assertEqual(len(builds), 2)
                base["SystemUI.apk"] = b"updated-system-ui"
                identity.system_ui_digest = hashlib.sha256(base["SystemUI.apk"]).hexdigest()
                updated = resources.prepare_payload(plugin, config, identity, run)
                self.assertNotEqual(first, updated)
                self.assertEqual(len(builds), 3)

    def test_changed_image_is_rejected_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "waydroid.cfg").write_text("[waydroid]\nimages_path=/images\n")
            resources_root = root / "resources/display"
            resources_root.mkdir(parents=True)
            tools = root / "tools"
            tools.mkdir()
            (tools / "manifest.json").write_text('{}')
            def run(args, **kwargs):
                Path(args[2].split(" ", 2)[2]).write_bytes(b"changed")
            with patch.object(resources, "resource_tools", return_value=tools), patch.object(resources.subprocess, "run") as compiler:
                with self.assertRaisesRegex(RuntimeError, "image changed"):
                    resources.prepare_payload(root, root, SimpleNamespace(framework_digest="old", system_ui_digest="old"), run)
                compiler.assert_not_called()
