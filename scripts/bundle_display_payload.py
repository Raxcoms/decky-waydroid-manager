import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py_modules"))
from waydroid_manager.display_payload import VendorIdentity, digest, elf_machine, select_payload


def bundle(build: Path, identity: VendorIdentity, output: Path) -> Path:
    files = {
        "hwcomposer.waydroid.so": "composerSha256",
        "libhwc2on1adapter.so": "adapterSha256",
        "WaydroidManagerExternalDisplay.apk": "overlaySha256",
        "wayland_tablet.idc": "inputConfigSha256",
        "display_settings.xml": "displaySettingsSha256",
        "WaydroidManagerNavigationBar.apk": "navigationOverlaySha256",
    }
    metadata = {
        "vendorFingerprint": identity.fingerprint,
        "sdk": identity.sdk,
        "stockComposerSha256": identity.composer_digest,
        "stockAdapterSha256": identity.adapter_digest,
        "elfMachine": identity.machine,
        "stockSystemUiSha256": identity.system_ui_digest,
    }
    if (build / "system-ui.sha256").read_text().strip() != identity.system_ui_digest:
        raise RuntimeError("The navigation overlay was built against a different System UI")
    for name, checksum in files.items():
        source = build / name
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"Missing payload build output: {name}")
        if name.endswith(".so") and elf_machine(source) != identity.machine:
            raise RuntimeError(f"Payload architecture mismatch: {name}")
        metadata[checksum] = digest(source)
    manifest = build / "source-manifest.xml"
    if not manifest.is_file():
        raise RuntimeError("The payload source manifest is missing")
    metadata["sourceManifestSha256"] = digest(manifest)
    target = output / identity.composer_digest
    target.mkdir(parents=True, exist_ok=False)
    try:
        for name in (*files, "source-manifest.xml", "composer-source.patch", "adapter-source.patch", "NOTICE.txt"):
            shutil.copyfile(build / name, target / name)
        (target / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        select_payload(output, identity)
    except Exception:
        shutil.rmtree(target)
        raise
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bundle a tested external-display build for a vendor ABI")
    parser.add_argument("build", type=Path)
    parser.add_argument("identity", type=Path, help="JSON representation of the inspected VendorIdentity")
    parser.add_argument("--output", type=Path, default=ROOT / "bin/display-payloads")
    args = parser.parse_args()
    identity = VendorIdentity(**json.loads(args.identity.read_text(encoding="utf-8")))
    print(bundle(args.build, identity, args.output))
