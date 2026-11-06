import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def package(output: Path) -> Path:
    target = output / "waydroid-manager"
    target.mkdir(parents=True, exist_ok=False)
    for name in ("plugin.json", "package.json", "README.md", "LICENSE", "main.py"):
        shutil.copy2(ROOT / name, target / name)
    for name in ("bin", "dist", "docs", "py_modules"):
        shutil.copytree(ROOT / name, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for script in (target / "bin").iterdir():
        if script.is_file():
            script.chmod(0o755)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage the Decky plugin in an empty output directory")
    parser.add_argument("output", type=Path, nargs="?", default=Path("out"))
    args = parser.parse_args()
    print(package(args.output))
