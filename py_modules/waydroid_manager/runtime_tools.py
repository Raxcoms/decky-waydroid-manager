from pathlib import Path
import json

from .display_payload import digest, elf_machine


def resource_tools(plugin: Path) -> Path:
    machine = elf_machine(Path("/usr/bin/python3").resolve())
    tools = plugin / "bin/display-tools" / str(machine)
    metadata = json.loads((tools / "manifest.json").read_text())
    if metadata.get("elfMachine") != machine or not {"aapt2", "openssl"}.issubset(metadata.get("files", {})):
        raise RuntimeError("The plugin has no resource tools for this host")
    for relative, expected in metadata["files"].items():
        path = tools / relative
        if (Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink()
                or not path.is_file() or digest(path) != expected):
            raise RuntimeError("The private Android resource tools failed validation")
    return tools

