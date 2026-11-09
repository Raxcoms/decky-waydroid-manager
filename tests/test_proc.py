from pathlib import Path
import os
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.proc import clean_env, steam_session, steam_wayland_socket


@unittest.skipIf(os.name == "nt", "Requires Unix display sockets")
class SteamDisplayTests(unittest.TestCase):
    def test_prefers_live_gamescope_socket_without_xwayland(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc, runtime = root / "proc", root / "run"
            proc.mkdir()
            runtime.mkdir()
            primary, other = runtime / "gamescope", runtime / "wayland"
            with socket.socket(socket.AF_UNIX) as gamescope, socket.socket(socket.AF_UNIX) as desktop:
                gamescope.bind(str(primary))
                desktop.bind(str(other))
                for pid, name, display in (
                    ("1", "steam", "GAMESCOPE_WAYLAND_DISPLAY=stale\0WAYLAND_DISPLAY=wayland"),
                    ("2", "steamwebhelper", "GAMESCOPE_WAYLAND_DISPLAY=gamescope"),
                ):
                    process = proc / pid
                    process.mkdir()
                    (process / "cmdline").write_bytes(f"/usr/bin/{name}\0".encode())
                    (process / "environ").write_bytes(
                        f"XDG_RUNTIME_DIR={runtime}\0XDG_DATA_HOME={root / 'custom-share'}\0{display}\0".encode()
                    )
                self.assertEqual(steam_wayland_socket(proc.stat().st_uid, proc), primary)
                self.assertEqual(steam_session(proc.stat().st_uid, proc).data_home, root / "custom-share")
                primary.unlink()
                self.assertEqual(steam_wayland_socket(proc.stat().st_uid, proc), other)

    def test_resolves_aliases_but_does_not_guess_between_equal_steam_sockets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, companion, alias = (root / name for name in ("primary", "companion", "alias"))
            with socket.socket(socket.AF_UNIX) as first, socket.socket(socket.AF_UNIX) as second:
                first.bind(str(primary))
                second.bind(str(companion))
                alias.symlink_to(primary)
                for pid, display in (("1", primary), ("2", alias)):
                    process = root / pid
                    process.mkdir()
                    (process / "cmdline").write_bytes(b"/usr/bin/steam\0")
                    (process / "environ").write_bytes(f"GAMESCOPE_WAYLAND_DISPLAY={display}\0".encode())
                self.assertEqual(steam_wayland_socket(os.getuid(), root), primary)
                alias.unlink()
                alias.symlink_to(companion)
                self.assertIsNone(steam_wayland_socket(os.getuid(), root))


class ProcessEnvironmentTests(unittest.TestCase):
    def test_preserves_host_libraries_and_removes_bundled_python(self):
        values = {"LD_LIBRARY_PATH": "/tmp/decky", "LD_LIBRARY_PATH_ORIG": "/host/libs",
                  "PYTHONHOME": "/tmp/decky", "PYTHONPATH": "/tmp/decky", "HOME": "/home/user"}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(clean_env(), {"LD_LIBRARY_PATH": "/host/libs", "HOME": "/home/user"})
            self.assertEqual(dict(os.environ), values)

    def test_removes_bundled_search_path_without_host_override(self):
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/decky"}, clear=True):
            self.assertEqual(clean_env(), {})
