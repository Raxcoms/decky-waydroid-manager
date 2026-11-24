import json
import asyncio
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from waydroid_manager.host_storage import BLOCK, FILESYSTEM, HostVolume, StorageMonitor, folder_name, mounted_volumes, storage_changed
from waydroid_manager.proc import process_identity
from waydroid_manager.shared_storage import SharedStorage


class HostStorageTests(unittest.TestCase):
    def test_only_mounted_non_system_filesystems_are_shared(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            objects = {}
            for name, system, ignore, mounted in (("sd", False, False, True), ("root", True, False, True),
                                                 ("hidden", False, True, True), ("empty", False, False, False)):
                objects[name] = {
                    BLOCK: {key: {"data": value} for key, value in
                            {"HintSystem": system, "HintIgnore": ignore, "IdLabel": "Games", "IdUUID": name}.items()},
                    FILESYSTEM: {"MountPoints": {"data": [list(os.fsencode(path) + b"\0")] if mounted else []}},
                }
            run = Mock(return_value=json.dumps({"data": [objects]}))
            self.assertEqual(mounted_volumes(run), [HostVolume("sd", "Games", path.resolve())])
            self.assertNotIn("sh", run.call_args.args[0])

    def test_labels_cannot_escape_the_host_folder(self):
        self.assertEqual(folder_name("../Games/SD\\Card\x00"), "_Games_SD_Card_")
        self.assertEqual(folder_name(".."), "Storage")

    def test_monitor_refreshes_on_drive_removal_or_invalidated_mounts(self):
        def signal(member, *args):
            return storage_changed({"member": member, "payload": {"data": list(args)}})

        self.assertTrue(signal("InterfacesAdded", "/sd", {FILESYSTEM: {}}))
        self.assertTrue(signal("InterfacesRemoved", "/sd", [FILESYSTEM]))
        self.assertTrue(signal("PropertiesChanged", FILESYSTEM, {}, ["MountPoints"]))
        self.assertTrue(signal("PropertiesChanged", BLOCK, {"IdLabel": "Card"}, []))
        self.assertFalse(signal("InterfacesRemoved", "/sd", [BLOCK]))
        self.assertFalse(signal("PropertiesChanged", BLOCK, {"Size": 42}, []))

    def test_provider_restart_removes_old_volume_names_and_retries_partial_home_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = SharedStorage(Path("config"), Path("plugin"), root)
            storage.process = (1, "old")
            storage.home = root / "home"
            storage.volumes = {"old-card": (None, "Old card")}
            (root / "view/Old card").mkdir(parents=True)
            storage._connect_provider = Mock(side_effect=lambda run: setattr(storage, "process", (2, "new")))
            storage._folder = Mock()
            storage._mount = Mock(side_effect=lambda name, source, run: storage.mounts.update({name: ()}))
            with patch("waydroid_manager.shared_storage.process_identity", return_value=(2, "new")):
                storage._initialize_mounts(Mock())
                self.assertFalse((root / "view/Old card").exists())
                self.assertEqual(set(storage.mounts), {"", "Home"})
                del storage.mounts["Home"]
                storage._mount.reset_mock()
                storage._initialize_mounts(Mock())
                self.assertEqual([call.args[0] for call in storage._mount.call_args_list], ["Home"])
                storage._connect_provider.assert_called_once()

    def test_cloned_volume_uuids_do_not_merge_two_drives(self):
        with tempfile.TemporaryDirectory() as directory:
            mount = list(os.fsencode(directory) + b"\0")
            objects = {name: {
                BLOCK: {"HintSystem": {"data": False}, "IdUUID": {"data": "same-uuid"}},
                FILESYSTEM: {"MountPoints": {"data": [mount]}},
            } for name in ("first", "second")}
            run = Mock(return_value=json.dumps({"data": [objects]}))
            self.assertEqual({volume.identity for volume in mounted_volumes(run)}, {"first", "second"})

    def test_duplicate_labels_keep_distinct_mounts_and_removal_releases_only_that_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = SharedStorage(Path("config"), Path("plugin"), root)
            storage.ready = True
            storage.guest = (123, "boot")
            storage.process = (456, "provider")
            storage.user = "7"
            storage.uid, storage.gid = os.getuid(), os.getgid()
            storage.home = root / "home"
            storage.mounts = {"": (), "Home": (1, "/data/user/7/waydroid.manager.storage/files/Host/Home", "2", "0")}
            (root / "view").mkdir()
            storage._unmount = Mock(side_effect=lambda name, run: storage.mounts.pop(name))
            storage._mount = Mock(side_effect=lambda name, source, run: storage.mounts.update({name: (1, str(source), "3", "0")}))
            first, second = HostVolume("one", "Games", root / "one"), HostVolume("two", "Games", root / "two")
            with (patch("waydroid_manager.shared_storage.process_identity", return_value=storage.process),
                  patch("waydroid_manager.shared_storage.container_identity", return_value=storage.guest),
                  patch("waydroid_manager.shared_storage.mounted_volumes", return_value=[first, second]) as discover):
                storage.refresh(Mock())
                names = {identity: name for identity, (_, name) in storage.volumes.items()}
                self.assertNotEqual(names["one"], names["two"])
                storage.refresh(Mock())
                self.assertEqual(storage._mount.call_count, 2)
                discover.return_value = [second]
                storage.refresh(Mock())
                storage._unmount.assert_called_once()
                self.assertEqual(set(storage.volumes), {"two"})
                self.assertEqual(storage.volumes["two"][1], names["two"])


@unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os, "pidfd_open"), "Requires Linux pidfds")
class StorageProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_exit_notifies_once_and_releases_the_watcher(self):
        changed = asyncio.Event()
        monitor = StorageMonitor(changed.set)
        child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
        try:
            monitor.watch_process(process_identity(child.pid))
            child.stdin.close()
            await asyncio.wait_for(changed.wait(), 2)
            self.assertIsNone(monitor.handle)
            self.assertIsNone(monitor.process)
        finally:
            child.kill()
            child.wait()
            child.stdin.close()
            await monitor.close()
