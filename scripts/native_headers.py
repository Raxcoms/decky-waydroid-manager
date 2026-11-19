"""Generate only the protocol headers needed by the native display extension."""

import argparse
from pathlib import Path
import re
import subprocess


def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def generate(source: Path, output: Path, hidl_gen: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    vndk = source / "vndk/include"
    include_names = {"include", "include_vndk", "include_private", "include_types", "include_cpp",
                     "include_ndk", "include_platform", "gen"}
    includes = set()
    for path in vndk.rglob("*.h"):
        relative = path.relative_to(vndk)
        for index, part in enumerate(relative.parts[:-1]):
            if part in include_names:
                includes.add(vndk.joinpath(*relative.parts[:index + 1]))
    for path in vndk.rglob("MQDescriptorBase.h"):
        includes.add(path.parent.parent)
    (output / "includes.txt").write_text("\n".join(map(str, sorted(includes))) + "\n")

    ffi = source / "external/libffi"
    with (ffi / "include/ffi.h.in").open("rb") as template, (output / "ffi_gen.h").open("wb") as target:
        run("bash", ffi / "gen_ffi_header.sh", stdin=template, stdout=target)

    version_template = source / "external/wayland/src/wayland-version.h.in"
    version = re.search(r"version\s*:\s*'([^']+)'", (source / "external/wayland/meson.build").read_text())[1]
    text = version_template.read_text()
    for name, value in zip(("MAJOR", "MINOR", "MICRO"), version.split(".")):
        text = text.replace(f"@WAYLAND_VERSION_{name}@", value)
    text = text.replace("@WAYLAND_VERSION@", version)
    (output / "wayland-version.h").write_text(text)

    wayland = source / "external/wayland"
    scanner = output / "wayland-scanner"
    run("cc", "-I", wayland, "-I", wayland / "src", "-I", output,
        wayland / "src/scanner.c", wayland / "src/wayland-util.c", "-lexpat", "-o", scanner)

    composer_files = [path for path in (source / "hardware/waydroid/hwcomposer").rglob("*")
                      if path.suffix in {".h", ".cpp"}]
    required = {"wayland"}
    for path in composer_files:
        required.update(re.findall(r'[<"]([^<>"/]+)-client-protocol\.h[>"]', path.read_text()))
    candidates = [source / "external/wayland/protocol/wayland.xml",
                  source / "hardware/waydroid/hwcomposer/wayland-android.xml",
                  *sorted((source / "external/wayland-protocols").rglob("*.xml"))]
    xmls = [xml for xml in candidates if xml.stem in required]
    missing = required - {xml.stem for xml in xmls}
    if missing:
        raise RuntimeError(f"Missing Wayland protocols: {', '.join(sorted(missing))}")
    for xml in xmls:
        run(scanner, "client-header", xml, output / f"{xml.stem}-client-protocol.h")
        run(scanner, "private-code", xml, output / f"{xml.stem}-protocol.c")
    protocols = [output / f"{xml.stem}-protocol.c" for xml in xmls if xml.stem != "wayland"]
    (output / "protocols.cmake").write_text("set(wayland_protocol_sources\n"
                                          + "\n".join(f'  "{path}"' for path in protocols) + "\n)\n")

    packages = set()
    for header in composer_files:
        for module, version in re.findall(r"vendor/waydroid/([^/]+)/(\d+\.\d+)/", header.read_text()):
            packages.add(f"vendor.waydroid.{module}@{version}")
    # Older interface versions remain imports of the current interface.
    for hal in (source / "hardware/waydroid/interfaces").rglob("*.hal"):
        if any(f"vendor.waydroid.{hal.parts[-3]}@" in package for package in packages):
            match = re.search(r"package\s+([^;]+);", hal.read_text())
            if match:
                packages.add(match[1])
    roots = [f"-rvendor.waydroid:{source / 'hardware/waydroid/interfaces'}",
             f"-randroid.hardware:{source / 'hardware/interfaces'}",
             f"-randroid.hidl:{source / 'system/libhidl/transport'}"]
    for package in sorted(packages | {"android.hardware.graphics.composer@2.1"}):
        run(hidl_gen, "-o", output, "-Lc++-headers", *roots, package)
        if package.startswith("vendor."):
            run(hidl_gen, "-o", output, "-Lc++-sources", *roots, package)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--hidl-gen", type=Path, required=True)
    args = parser.parse_args()
    generate(args.source.resolve(), args.output.resolve(), args.hidl_gen.resolve())
