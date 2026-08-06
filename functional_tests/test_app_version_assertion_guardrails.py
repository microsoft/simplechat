#!/usr/bin/env python3
# test_app_version_assertion_guardrails.py
"""
Functional test for app version assertion guardrails.
Version: 0.250.126
Implemented in: 0.250.126

This test prevents functional tests from reintroducing exact config.py VERSION
checks that fail after normal application version bumps.
"""

import ast
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOTS = [
    REPO_ROOT / "functional_tests",
    REPO_ROOT / "ui_tests",
]
EXCLUDED_RELATIVE_PATHS = {
    "functional_tests/test_app_version_assertion_guardrails.py",
    "functional_tests/test_support/versioning.py",
}

VERSION_ASSIGNMENT_ASSERT_RE = re.compile(
    r"VERSION\s*=\s*[\"']\d+\.\d+\.\d+[\"']"
)
READ_CONFIG_VERSION_EXACT_RE = re.compile(
    r"read_config_version\(\)\s*(?:==|!=)\s*[\"']\d+\.\d+\.\d+[\"']"
    r"|[\"']\d+\.\d+\.\d+[\"']\s*(?:==|!=)\s*read_config_version\(\)"
)
CURRENT_VERSION_EXACT_RE = re.compile(
    r"current_version\s*(?:==|!=)\s*CURRENT_VERSION"
    r"|CURRENT_VERSION\s*(?:==|!=)\s*current_version",
    re.IGNORECASE,
)
CONFIG_TARGET_RE = re.compile(
    r"\bconfig(?:_\w+)?\b|\bcontent\b|CONFIG_FILE|config\.py|"
    r"read_text\([^)]*config\.py|_read\(CONFIG_FILE\)|read_text\(CONFIG_FILE\)",
    re.IGNORECASE,
)
DOCUMENTATION_TARGET_RE = re.compile(
    r"fix_doc|feature_doc|release_notes|doc_content|documentation",
    re.IGNORECASE,
)


def _relative_path(path):
    return path.relative_to(REPO_ROOT).as_posix()


def _is_excluded(path):
    relative_path = _relative_path(path)
    return (
        relative_path in EXCLUDED_RELATIVE_PATHS
        or "/test_support/" in relative_path
    )


def _is_brittle_app_version_assertion(assert_source):
    flat_source = " ".join(assert_source.split())

    if READ_CONFIG_VERSION_EXACT_RE.search(flat_source):
        return True
    if CURRENT_VERSION_EXACT_RE.search(flat_source):
        return True
    if (
        VERSION_ASSIGNMENT_ASSERT_RE.search(flat_source)
        and CONFIG_TARGET_RE.search(flat_source)
        and not DOCUMENTATION_TARGET_RE.search(flat_source)
    ):
        return True

    return False


def test_app_version_assertions_use_shared_minimum_helper():
    """Validate tests use shared >= app-version checks instead of exact equality."""
    print("Testing app version assertion guardrails...")

    violations = []
    for root in TEST_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if _is_excluded(path):
                continue

            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assert):
                    continue

                assert_source = ast.get_source_segment(source, node) or ""
                if _is_brittle_app_version_assertion(assert_source):
                    violations.append(f"{_relative_path(path)}:{node.lineno}: {assert_source.strip()}")

    assert not violations, (
        "Use assert_app_version_at_least(...) from test_support.versioning "
        "instead of exact config.py VERSION assertions:\n" + "\n".join(violations)
    )

    print("App version assertion guardrails passed.")
    return True


if __name__ == "__main__":
    try:
        test_app_version_assertions_use_shared_minimum_helper()
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)
