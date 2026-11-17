import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from waydroid_manager.host_storage import BLOCK, FILESYSTEM, HostVolume, folder_name, mounted_volumes
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
            storage.uid, storage.gid = os.getuid(), os.getgid()
            storage.home = root / "home"
            storage.mounts = {"Home": (1, "/data/media/0/Host/Home", "2", "0")}
            (root / "view").mkdir()
            storage._unmount = Mock(side_effect=lambda name, run: storage.mounts.pop(name))
            storage._mount = Mock(side_effect=lambda name, source, run: storage.mounts.update({name: (1, str(source), "3", "0")}))
            first, second = HostVolume("one", "Games", root / "one"), HostVolume("two", "Games", root / "two")
            with (patch("waydroid_manager.shared_storage.container_identity", return_value=storage.guest),
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
