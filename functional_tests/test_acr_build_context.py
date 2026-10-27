# test_acr_build_context.py
"""
Functional regression for host artifacts overwriting ACR container dependencies.
Version: 0.261.389
Implemented in: 0.261.389

Uses the installed Azure CLI's actual archive builder on a synthetic checkout.
No Azure credentials, network access, or Docker daemon are required.
"""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_acr_archive_excludes_host_artifacts(tmp_path):
    """Keep source and manifests, but exclude host dependencies and generated output."""
    az = shutil.which("az")
    if az is None:
        pytest.skip("Azure CLI is required to exercise its actual ACR archive builder")
    bundled_python = Path(az).resolve().parent.parent / "python.exe"
    python = str(bundled_python) if bundled_python.is_file() else sys.executable
    probe = subprocess.run(
        [python, "-c", "from azure.cli.command_modules.acr import _archive_utils"],
        capture_output=True, text=True, check=False,
    )
    if probe.returncode:
        pytest.skip(f"Azure CLI archive module unavailable to {python}: {probe.stderr}")

    context = tmp_path / "context"
    context.mkdir()
    shutil.copyfile(REPO_ROOT / ".dockerignore", context / ".dockerignore")
    included = {
        "application/v2_ui/package.json",
        "application/v2_ui/package-lock.json",
        "application/v2_ui/src/main.tsx",
        "application/single_app/config.py",
        "application/single_app/static/js/chat.js",
        "docker-customization/pip.conf",
        "LICENSE",
    }
    excluded = {
        "application/v2_ui/node_modules/.bin/tsc",
        "application/v2_ui/node_modules/typescript/bin/tsc",
        "application/v2_ui/node_modules/@esbuild/win32-x64/esbuild.exe",
        "application/v2_ui/dist/index.html",
        "application/single_app/static/v2/assets/stale.js",
        "application/single_app/native/onenote_extractor/target/release/extractor",
        "application/single_app/native/onenote_extractor/bin/extractor",
        "application/single_app/flask_session/session",
        "application/single_app/uploaded_openapi_files/private.json",
        "application/single_app/instance/private.json",
        "application/single_app/__pycache__/config.pyc",
        "application/v2_ui/.env.local",
        "application/single_app/.env",
        "deployers/.azure/environment/.env",
        "docs/index.md",
    }
    dockerfile = "application/single_app/Dockerfile"
    for name in included | excluded | {dockerfile}:
        path = context / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")

    script = """
import sys, tarfile
from pathlib import Path
from azure.cli.command_modules.acr import _archive_utils

root, archive = map(Path, sys.argv[1:3])
dockerfile = 'application/single_app/Dockerfile'
_archive_utils._pack_source_code(
    str(root), str(archive), str(root / dockerfile), dockerfile,
)
with tarfile.open(archive) as tar:
    for member in tar.getmembers():
        if member.isfile():
            print(member.name)
"""
    result = subprocess.run(
        [python, "-c", script, str(context), str(tmp_path / "context.tar.gz")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    archived = set(result.stdout.splitlines())
    assert included <= archived, f"Required build inputs missing: {included - archived}"
    assert not excluded & archived, f"Host artifacts leaked into ACR context: {excluded & archived}"
