# prepare_model_catalog_sdk.py
"""Verify compiler SDK pins before preparing the locked CI install directory."""

import json
from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = ROOT / ".github" / "dependencies" / "model-catalog"


def verify_install_command(source, dependencies):
    commands = re.findall(r"npm install --ignore-scripts --no-save ([^\n]+)", source)
    expected = " ".join(f"{name}@{version}" for name, version in dependencies.items())
    if commands != [expected]:
        raise ValueError("Regenerate and review the SDK lock before changing compiler SDK selections.")


def main():
    manifest = json.loads((DEPENDENCIES / "package.json").read_text(encoding="utf-8"))
    source = (ROOT / ".github" / "workflows" / "refresh-model-catalog.lock.yml").read_text(encoding="utf-8")
    verify_install_command(source, manifest["dependencies"])
    destinations = [ROOT / name for name in ("package.json", "package-lock.json")]
    if any(path.exists() for path in destinations):
        raise FileExistsError("Refusing to overwrite an existing workspace npm manifest or lock.")
    for path in destinations:
        shutil.copyfile(DEPENDENCIES / path.name, path)


if __name__ == "__main__":
    main()
