"""Check applied upstream patches against the original source manifest."""

from collections import defaultdict
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def patch_ids(content: bytes) -> set[str]:
    result = subprocess.run(["git", "patch-id", "--stable"], input=content, capture_output=True, check=True)
    return {line.split()[0] for line in result.stdout.decode().splitlines()}


def verify(root: Path) -> bool:
    projects = {entry.attrib.get("path", entry.attrib["name"]): entry.attrib["revision"]
                for entry in ET.parse(root / "source-manifest.xml").findall("project")}
    groups = defaultdict(list)
    patches = root / "vendor/extra/waydroid-patches/base-patches-33"
    for patch in patches.rglob("*.patch"):
        groups[patch.parent.relative_to(patches).as_posix()].append(patch)
    missing = []
    for project, files in groups.items():
        history = subprocess.check_output(["git", "-C", str(root / project), "log", "-p",
                                           f"{projects[project]}..HEAD"])
        applied = patch_ids(history)
        for patch in files:
            expected = patch_ids(patch.read_bytes())
            if not expected or not expected.issubset(applied):
                missing.append(patch.relative_to(patches).as_posix())
    if missing:
        print("Unverified Waydroid patches:")
        print("\n".join(missing))
        return False
    print("All upstream Waydroid patches match the recorded source revisions")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if verify(Path(sys.argv[1])) else 1)
