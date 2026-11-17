"""Validate and locally sign the owned, image-independent storage provider."""

import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from .display_payload import digest
from .runtime_tools import resource_tools
from .proc import clean_env


PROVIDER_PATH = "system/app/WaydroidManagerStorage/WaydroidManagerStorage.apk"


def unsigned_provider(plugin: Path) -> Path:
    root = plugin / "bin/storage-provider"
    metadata = json.loads((root / "manifest.json").read_text())
    apk = root / "provider-unsigned.apk"
    if (metadata.get("schemaVersion") != 1 or metadata.get("file") != apk.name
            or apk.is_symlink() or digest(apk) != metadata.get("sha256")):
        raise RuntimeError("The Host storage provider failed validation")
    with zipfile.ZipFile(apk) as archive:
        if not archive.read("classes.dex").startswith(b"dex\n"):
            raise RuntimeError("The Host storage provider has no valid runtime code")
    return apk


def prepare_provider(plugin: Path, config: Path) -> Path:
    unsigned = unsigned_provider(plugin)
    tools = resource_tools(plugin)
    builder = Path(__file__).with_name("resource_builder.py")
    recipe = hashlib.sha256(unsigned.read_bytes() + builder.read_bytes() + (tools / "manifest.json").read_bytes()).hexdigest()
    cache = config / "waydroid-manager-resources"
    cache.mkdir(mode=0o700, exist_ok=True)
    if cache.is_symlink():
        raise RuntimeError("Invalid Host storage cache")
    with (cache / "prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        target = cache / ("provider-" + recipe)
        apk = target / "WaydroidManagerStorage.apk"
        checksum = target / "sha256"
        if (apk.is_file() and not apk.is_symlink() and checksum.is_file()
                and digest(apk) == checksum.read_text()):
            return apk
        with tempfile.TemporaryDirectory(prefix="provider-build-", dir=cache) as directory:
            staging = Path(directory)
            output = staging / apk.name
            try:
                subprocess.run(["/usr/bin/python3", "-I", str(builder), "--sign", str(unsigned), str(output),
                                str(cache / "signing"), str(tools)], env=clean_env(), check=True,
                               capture_output=True, timeout=60)
            except subprocess.CalledProcessError as error:
                raise RuntimeError("Could not prepare the Host storage provider: " + error.stderr.decode(errors="replace")[:1000]) from error
            (staging / "sha256").write_text(digest(output))
            if target.exists():
                if target.is_symlink():
                    raise RuntimeError("Invalid Host storage cache entry")
                shutil.rmtree(target)
            staging.rename(target)
        return apk
