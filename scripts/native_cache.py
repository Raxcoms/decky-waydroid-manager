"""Describe internal build caches for every supported native profile and host."""

import hashlib
import json
from pathlib import Path

from build_native import ROOT, recipe_digest


def entries() -> list[dict]:
    native = []
    for path in sorted((ROOT / "android/native/profiles").glob("*.json")):
        dependencies = json.loads(path.read_text())["dependencies"]
        archives = sorted((entry["name"], entry.get("treeSha256") or entry["sha256"]) for entry in dependencies)
        source_digest = hashlib.sha256(json.dumps(archives).encode()).hexdigest()
        native.append({"profile": path.stem, "path": "out/display-native", "sources": source_digest,
                       "key": f"display-native-Linux-{path.stem}-{recipe_digest(path)}"})
    digest = hashlib.sha256()
    for name in ("scripts/bundle_runtime_tools.py", "android/native/runtime-tools.json", "native/host/home-mount.c"):
        digest.update((ROOT / name).read_bytes())
    tools = [{**tool, "path": "out/display-tools",
              "key": f"display-tools-{tool['runner']}-{digest.hexdigest()}"}
             for tool in json.loads((ROOT / "android/native/runtime-tools.json").read_text())]
    return native + tools


if __name__ == "__main__":
    print(json.dumps(entries()))
