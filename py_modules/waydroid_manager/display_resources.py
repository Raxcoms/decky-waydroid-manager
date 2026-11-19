"""Prepare image-specific resources locally without changing installed images."""

import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from .display_payload import digest
from .runtime_tools import resource_tools
from .image_files import extract
from .proc import clean_env


RESOURCE_FILES = {
    "system/product/overlay/WaydroidManagerExternalDisplay.apk": "WaydroidManagerExternalDisplay.apk",
    "system/product/overlay/WaydroidManagerNavigationBar.apk": "WaydroidManagerNavigationBar.apk",
    "system/usr/idc/wayland_tablet.idc": "wayland_tablet.idc",
    "vendor/etc/display_settings.xml": "display_settings.xml",
}



def prepare_payload(plugin: Path, config: Path, identity, run, progress=lambda stage: None) -> dict[str, Path]:
    progress("checking")
    tools = resource_tools(plugin)
    resources = plugin / "resources/display"
    builder = Path(__file__).with_name("resource_builder.py")
    recipe = hashlib.sha256(builder.read_bytes())
    for path in sorted(resources.rglob("*")):
        if path.is_file():
            recipe.update(path.relative_to(resources).as_posix().encode())
            recipe.update(path.read_bytes())
    recipe.update((tools / "manifest.json").read_bytes())
    recipe.update(identity.system_ui_digest.encode())
    recipe.update(identity.framework_digest.encode())
    key = recipe.hexdigest()
    cache = config / "waydroid-manager-resources"
    cache.mkdir(mode=0o700, exist_ok=True)
    if cache.is_symlink():
        raise RuntimeError("Invalid Android resource cache")
    with (cache / "prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        target = cache / key
        manifest = target / "manifest.json"
        if manifest.is_file() and not target.is_symlink() and not manifest.is_symlink():
            try:
                saved = json.loads(manifest.read_text())
                if isinstance(saved, dict) and set(saved) == set(RESOURCE_FILES.values()) and all(
                        (target / name).is_file() and not (target / name).is_symlink()
                        and digest(target / name) == expected for name, expected in saved.items()):
                    progress("ready")
                    return {relative: target / name for relative, name in RESOURCE_FILES.items()}
            except (OSError, ValueError):
                pass
        progress("extracting")
        with tempfile.TemporaryDirectory(prefix="build-", dir=cache) as directory:
            staging = Path(directory)
            framework = extract(config, "system.img", ("/system/framework/framework-res.apk",), staging / "framework-res.apk", run)
            system_ui = extract(config, "system.img", ("/system_ext/priv-app/SystemUI/SystemUI.apk",
                                 "/system/system_ext/priv-app/SystemUI/SystemUI.apk"), staging / "SystemUI.apk", run)
            if digest(framework) != identity.framework_digest or digest(system_ui) != identity.system_ui_digest:
                raise RuntimeError("The Android image changed during resource preparation")
            output = staging / "output"
            output.mkdir()
            progress("building")
            try:
                subprocess.run(["/usr/bin/python3", "-I", str(builder), str(resources), str(tools), str(framework),
                                str(system_ui), str(cache / "signing"), str(output)], env=clean_env(), check=True,
                               capture_output=True, timeout=120)
            except subprocess.CalledProcessError as error:
                detail = (error.stderr or b"").decode(errors="replace").strip()
                raise RuntimeError("Could not build Android display resources: " + detail[:2000]) from error
            for name in ("wayland_tablet.idc", "display_settings.xml"):
                shutil.copyfile(resources / name, output / name)
            (output / "manifest.json").write_text(json.dumps({name: digest(output / name) for name in RESOURCE_FILES.values()}))
            if target.exists():
                if target.is_symlink():
                    raise RuntimeError("Invalid Android resource cache entry")
                shutil.rmtree(target)
            output.rename(target)
        progress("ready")
        return {relative: target / name for relative, name in RESOURCE_FILES.items()}
