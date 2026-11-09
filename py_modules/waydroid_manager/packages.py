from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import logging
import re
import shutil
import subprocess
import tempfile
from typing import BinaryIO
import zipfile

from .guest import stream_to_guest


MAX_SPLITS = 128


def check_result(output: str) -> None:
    if "Success" not in output.splitlines():
        raise RuntimeError(output or "PACKAGE_OPERATION_FAILED")


def install_apks(run, packages: dict[str, BinaryIO], commit=None) -> None:
    command = ["waydroid", "shell", "--", "pm"]
    sizes = {name: os.fstat(source.fileno()).st_size for name, source in packages.items()}
    size = sum(sizes.values())
    output = run([*command, "install-create", "-r", "-S", str(size)])
    match = re.search(r"^Success: created install session \[(\d+)\]$", output, re.MULTILINE)
    if not match:
        raise RuntimeError(output or "PACKAGE_OPERATION_FAILED")
    session = match[1]
    committed = False
    try:
        for name, source in packages.items():
            source.seek(0)
            output = stream_to_guest(run, source, "/system/bin/cmd", "package", "install-write",
                                     "-S", str(sizes[name]), session, name, "-", timeout=300)
            if not any(line == "Success" or line.startswith("Success:") for line in output.splitlines()):
                raise RuntimeError(output or "PACKAGE_OPERATION_FAILED")
        check_result(commit(session) if commit else run([*command, "install-commit", session], timeout=300))
        committed = True
    finally:
        if not committed:
            try:
                run([*command, "install-abandon", session])
            except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                logging.getLogger(__name__).warning("Could not abandon Android install session %s: %s", session, error)


def apk_members(archive: zipfile.ZipFile, suffix: str) -> list[tuple[zipfile.ZipInfo, str]]:
    if suffix == ".apk":
        if "AndroidManifest.xml" not in archive.namelist():
            raise RuntimeError("INVALID_APK_MANIFEST")
        return []
    packages = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".apk")]
    if not packages:
        raise RuntimeError("XAPK_NO_APKS")
    if len(packages) > MAX_SPLITS:
        raise RuntimeError("XAPK_TOO_MANY_APKS")
    names = [Path(item.filename).name for item in packages]
    if any(not name or "\\" in name for name in names) or len(set(names)) != len(names):
        raise RuntimeError("XAPK_INVALID_NAMES")
    return list(zip(packages, names))


@contextmanager
def stage_apks(archive: zipfile.ZipFile, members: list[tuple[zipfile.ZipInfo, str]], directory: Path = Path("/var/tmp")):
    if not members:
        yield {"base.apk": archive.fp}
        return
    if sum(item.file_size for item, _ in members) > shutil.disk_usage(directory).free:
        raise RuntimeError("PACKAGE_NO_SPACE")
    with ExitStack() as files:
        parts = {}
        for item, name in members:
            destination = files.enter_context(tempfile.TemporaryFile(dir=directory, buffering=0))
            with archive.open(item) as source:
                shutil.copyfileobj(source, destination)
            destination.flush()
            parts[name] = destination
        yield parts
