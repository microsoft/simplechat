#!/usr/bin/env python3
# test_public_workspace_manage_asset_versioning.py
"""
Functional test for public workspace manage asset versioning.
Version: 0.242.066
Implemented in: 0.242.058

This test ensures the manage public workspace page references its management
script with the application version so browsers do not reuse stale JavaScript
after deployments.
"""

import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT_DIR / "application" / "single_app" / "config.py"
MANAGE_PUBLIC_WORKSPACE_TEMPLATE = (
    ROOT_DIR
    / "application"
    / "single_app"
    / "templates"
    / "manage_public_workspace.html"
)
MANAGE_PUBLIC_WORKSPACE_JS = (
    ROOT_DIR
    / "application"
    / "single_app"
    / "static"
    / "js"
    / "public"
    / "manage_public_workspace.js"
)
FIX_DOC = (
    ROOT_DIR
    / "docs"
    / "explanation"
    / "fixes"
    / "PUBLIC_WORKSPACE_MANAGE_ASSET_VERSIONING_FIX.md"
)


def read_file_text(file_path):
    """Read a UTF-8 text file."""
    return file_path.read_text(encoding="utf-8")


def read_config_version():
    """Read the application version from config.py."""
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def test_manage_public_workspace_script_reference_is_versioned():
    """Verify the manage page references the script with the app version."""
    print("Testing public workspace manage script URL versioning...")

    source = read_file_text(MANAGE_PUBLIC_WORKSPACE_TEMPLATE)
    expected_reference = (
        "<script src=\"{{ url_for('static', filename='js/public/manage_public_workspace.js') }}"
        "?v={{ config['VERSION'] }}\"></script>"
    )
    unversioned_reference = (
        "<script src=\"{{ url_for('static', filename='js/public/manage_public_workspace.js') }}\"></script>"
    )

    assert expected_reference in source, "Expected manage script to include app-version cache busting."
    assert unversioned_reference not in source, "Unversioned manage script reference should not remain."

    print("PASS: public workspace manage script URL is versioned.")


def test_current_manage_public_workspace_script_parses_with_node():
    """Verify the current script still parses cleanly with Node.js."""
    print("Testing current public workspace manage script syntax with Node.js...")

    node_path = shutil.which("node")
    if not node_path:
        print("Node.js was not found; skipping parser check.")
        return

    result = subprocess.run(
        [node_path, "--check", str(MANAGE_PUBLIC_WORKSPACE_JS)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            "Expected manage_public_workspace.js to parse cleanly. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    print("PASS: current public workspace manage script parses cleanly.")


def test_fix_artifacts_are_in_sync():
    """Verify the versioned fix documentation exists and references the test."""
    print("Testing public workspace manage asset versioning artifact alignment...")

    version = read_config_version()
    assert version == "0.242.066", f"Expected config version 0.242.066, saw {version}."
    assert FIX_DOC.exists(), f"Expected fix documentation at {FIX_DOC}"

    fix_doc_source = read_file_text(FIX_DOC)
    assert "Fixed/Implemented in version: **0.242.058**" in fix_doc_source
    assert "functional_tests/test_public_workspace_manage_asset_versioning.py" in fix_doc_source
    assert "ui_tests/test_public_workspace_manage_script_parse.py" in fix_doc_source

    print("PASS: public workspace manage asset versioning artifacts are aligned.")


if __name__ == "__main__":
    tests = [
        test_manage_public_workspace_script_reference_is_versioned,
        test_current_manage_public_workspace_script_parses_with_node,
        test_fix_artifacts_are_in_sync,
    ]

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        test()

    print(f"\nResults: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)