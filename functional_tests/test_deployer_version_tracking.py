#!/usr/bin/env python3
# test_deployer_version_tracking.py
"""
Functional test for deployer version tracking.
Version: 0.241.086
Implemented in: 0.241.083

This test ensures the deployers folder includes a standalone version marker
for CI/CD logic tracking that is separate from the single_app version.
"""

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_workspace_file(relative_path: str) -> str:
    """Read a workspace file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_deployer_version_tracking() -> bool:
    """Validate deployer version tracking assets exist and stay decoupled."""
    print("🧪 Testing deployer version tracking")
    print("=" * 70)

    config_content = read_workspace_file("application/single_app/config.py")
    deployer_version = read_workspace_file("deployers/version.txt").strip()
    deployer_instruction_content = read_workspace_file(
        ".github/instructions/update_deployer_version.instructions.md"
    )
    feature_doc_content = read_workspace_file(
        "docs/explanation/features/v0.241.082/DEPLOYER_VERSION_TRACKING.md"
    )
    feature_index_content = read_workspace_file("docs/explanation/features/index.md")
    claude_content = read_workspace_file("CLAUDE.md")
    app_version_match = re.search(r'^\s*VERSION\s*=\s*"([^"]+)"', config_content, re.MULTILINE)

    assert app_version_match, "Expected config.py to define an application VERSION string."
    assert re.fullmatch(r"\d+\.\d+\.\d+", deployer_version), (
        "Expected deployers/version.txt to use a plain semantic version string."
    )
    assert "applyTo: 'deployers/**'" in deployer_instruction_content, (
        "Expected a targeted instruction file for deployers/** edits."
    )
    assert "include an update to `deployers/version.txt`" in deployer_instruction_content, (
        "Expected the deployer instruction file to require version bumps for deployer changes."
    )
    assert "separate from the application version" in feature_doc_content, (
        "Expected feature doc to describe the deployer version as separate from the application version."
    )
    assert "deployers/version.txt" in feature_doc_content, (
        "Expected feature doc to reference deployers/version.txt."
    )
    assert "Deployer Version Tracking" in feature_index_content, (
        "Expected features index to list the deployer version tracking feature."
    )
    assert "When modifying files under `deployers/`, increment `deployers/version.txt`" in claude_content, (
        "Expected CLAUDE.md to document deployer version bumps for deployer changes."
    )

    print("✅ Deployer version file exists with a CI/CD-friendly semantic version.")
    print("✅ Instruction and repo guidance require deployer version bumps for deployer changes.")
    print("✅ Feature documentation and index reference the standalone deployer version.")
    return True


if __name__ == "__main__":
    try:
        success = test_deployer_version_tracking()
    except Exception as ex:
        print(f"❌ Test failed: {ex}")
        raise

    sys.exit(0 if success else 1)