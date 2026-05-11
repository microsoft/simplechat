#!/usr/bin/env python3
# test_docs_json_gem_security_fix.py
"""
Functional test for docs json gem security fix.
Version: 0.239.136
Implemented in: 0.239.136

This test ensures the docs site bundle pins the Ruby json gem to a patched
version and that the lockfile resolves to a non-vulnerable release.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GEMFILE_PATH = ROOT / "docs" / "Gemfile"
LOCKFILE_PATH = ROOT / "docs" / "Gemfile.lock"
CONFIG_PATH = ROOT / "application" / "single_app" / "config.py"
FIX_DOC_PATH = ROOT / "docs" / "explanation" / "fixes" / "DOCS_JSON_GEM_SECURITY_FIX.md"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_docs_json_gem_security_fix() -> bool:
    print("Testing docs json gem security fix...")

    assert_contains(GEMFILE_PATH, 'gem "json", ">= 2.19.2"')
    assert_contains(LOCKFILE_PATH, 'json (2.19.2)')
    assert_contains(LOCKFILE_PATH, 'json (>= 2.19.2)')
    assert_contains(CONFIG_PATH, 'VERSION = "0.239.136"')
    assert_contains(FIX_DOC_PATH, 'Fixed/Implemented in version: **0.239.136**')

    print("Docs json gem security fix checks passed!")
    return True


if __name__ == "__main__":
    try:
        success = test_docs_json_gem_security_fix()
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)