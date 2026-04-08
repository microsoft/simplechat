#!/usr/bin/env python3
# test_postprovision_python_dependency_install.py
"""
Functional test for postprovision Python dependency installation.
Version: 0.237.064
Implemented in: 0.237.064

This test ensures the AZD postprovision hook avoids `pip install --user` when the
current Python interpreter is already inside a virtual environment.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
AZURE_YAML = REPO_ROOT / "deployers" / "azure.yaml"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_postprovision_python_dependency_install() -> bool:
    print("🧪 Testing postprovision Python dependency install handling")
    print("=" * 70)

    content = AZURE_YAML.read_text(encoding="utf-8")

    require_contains(content, "python_is_virtual_environment", "POSIX virtual environment detection helper")
    require_contains(content, "Test-PythonVirtualEnvironment", "Windows virtual environment detection helper")
    require_contains(content, "install_postprovision_python_dependencies", "POSIX dependency install helper")
    require_contains(content, "Install-PostprovisionPythonDependencies", "Windows dependency install helper")
    require_contains(content, "sys.prefix != getattr(sys, 'base_prefix', sys.prefix)", "virtual environment detection expression")
    require_contains(content, "python3 -m pip install -r ./bicep/requirements.txt", "POSIX venv-aware install command")
    require_contains(content, "python -m pip install -r .\\bicep\\requirements.txt", "Windows venv-aware install command")
    require_contains(content, "python3 -m pip install --user -r ./bicep/requirements.txt", "POSIX non-venv install command")
    require_contains(content, "python -m pip install --user -r .\\bicep\\requirements.txt", "Windows non-venv install command")

    print("✅ Postprovision hook detects Python virtual environments")
    print("✅ Postprovision hook skips --user when running inside a virtual environment")
    print("✅ Postprovision hook retains --user installs outside virtual environments")
    return True


if __name__ == "__main__":
    try:
        success = test_postprovision_python_dependency_install()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)