"""Check link dependencies against the SDK and declared Waydroid ABI extensions."""

from pathlib import Path
import subprocess


def symbols(tool: Path, files: list[Path], option: str) -> set[str]:
    result = subprocess.run([str(tool), "--dynamic", "--format=posix", option, *map(str, files)],
                            check=True, capture_output=True, text=True)
    return {fields[0].split("@", 1)[0] for line in result.stdout.splitlines()
            if len(fields := line.split()) >= 2 and len(fields[1]) == 1 and fields[1].isupper()}


def validate(tool: Path, library: Path, sdk: Path, extensions: list[str], required: list[str] = ()) -> None:
    exports = symbols(tool, sorted(sdk.glob("shared/**/*.so")), "--defined-only")
    imports = symbols(tool, [library], "--undefined-only")
    missing = imports - exports - set(extensions)
    if missing:
        raise RuntimeError("Native build uses undeclared runtime symbols: " + ", ".join(sorted(missing)))
    if missing := set(required) - imports:
        raise RuntimeError("Native build is missing required Waydroid ABI references: " + ", ".join(sorted(missing)))
