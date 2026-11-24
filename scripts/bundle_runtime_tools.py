"""Package the host resource compiler for offline image preparation."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile


def bundle(output: Path, expected_machine: int | None = None) -> Path:
    compiler = Path(shutil.which("aapt2") or "")
    signer = Path(shutil.which("openssl") or "")
    if not compiler.is_file() or not signer.is_file():
        raise RuntimeError("Install the build runner's aapt and openssl packages first")
    with compiler.open("rb") as file:
        header = file.read(20)
    machine = struct.unpack_from("<H", header, 18)[0]
    if expected_machine is not None and machine != expected_machine:
        raise RuntimeError("The runtime compiler does not match the requested host architecture")
    target = output / str(machine)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as directory:
        staging = Path(directory) / "bundle"
        build_tools(staging, compiler, signer, machine)
        previous = Path(directory) / "previous"
        if target.exists():
            target.rename(previous)
        try:
            staging.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise
    return target


def build_tools(target: Path, compiler: Path, signer: Path, machine: int) -> None:
    libraries = target / "lib"
    libraries.mkdir(parents=True)
    shutil.copyfile(compiler, target / "aapt2")
    (target / "aapt2").chmod(0o755)
    shutil.copyfile(signer, target / "openssl")
    (target / "openssl").chmod(0o755)
    linked = "\n".join(subprocess.check_output(["ldd", str(tool)], text=True) for tool in (compiler, signer))
    system_libraries = {"libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1"}
    sources = [compiler, signer]
    for line in linked.splitlines():
        match = re.search(r"=>\s+(/\S+)", line)
        if not match:
            continue
        library = Path(match[1])
        if library.name in system_libraries:
            continue
        shutil.copyfile(library, libraries / library.name)
        sources.append(library)
    notices = []
    packages = set()
    for source in sources:
        # Package records may use the paths from before usrmerge.
        owner = subprocess.check_output(["dpkg-query", "-S", f"*/{source.name}"], text=True).split(": ", 1)[0]
        package = owner.split(":", 1)[0]
        if package in packages:
            continue
        packages.add(package)
        copyright = Path("/usr/share/doc") / package / "copyright"
        if not copyright.is_file():
            raise RuntimeError(f"Missing runtime compiler copyright: {package}")
        notices.append(package + "\n\n" + copyright.read_text())
    (target / "NOTICE.txt").write_text("\n\n".join(notices))
    source = Path(__file__).resolve().parents[1] / "native/host/home-mount.c"
    subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target / "home-mount")],
                   check=True)
    files = {path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(target.rglob("*")) if path.is_file()}
    (target / "manifest.json").write_text(json.dumps({"schemaVersion": 1, "elfMachine": machine, "files": files}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--machine", type=int)
    args = parser.parse_args()
    print(bundle(args.output, args.machine))
