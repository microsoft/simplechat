# versioning.py
"""Shared SimpleChat version helpers for functional tests."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
VERSION_ASSIGNMENT_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"\s*$', re.MULTILINE)


def parse_simplechat_version(version):
    """Parse a SimpleChat dotted version string into an integer tuple."""
    normalized_version = str(version or "").strip().lstrip("vV")
    if not normalized_version:
        raise AssertionError("Version value is empty.")

    parts = normalized_version.split(".")
    if not all(part.isdigit() for part in parts):
        raise AssertionError(f"Version must contain only numeric dotted parts: {version!r}")

    return tuple(int(part) for part in parts)


def compare_simplechat_versions(left_version, right_version):
    """Compare two SimpleChat dotted versions."""
    left_parts = list(parse_simplechat_version(left_version))
    right_parts = list(parse_simplechat_version(right_version))
    max_length = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (max_length - len(left_parts)))
    right_parts.extend([0] * (max_length - len(right_parts)))

    if left_parts > right_parts:
        return 1
    if left_parts < right_parts:
        return -1
    return 0


def read_app_version(repo_root=None):
    """Read the current application VERSION from config.py."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    config_file = root / "application" / "single_app" / "config.py"
    config_source = config_file.read_text(encoding="utf-8")
    version_match = VERSION_ASSIGNMENT_RE.search(config_source)
    if not version_match:
        raise AssertionError(f"VERSION assignment not found in {config_file}")
    return version_match.group(1)


def assert_version_at_least(actual_version, minimum_version, label="version", reason=None):
    """Assert that a version is greater than or equal to a required minimum."""
    if compare_simplechat_versions(actual_version, minimum_version) < 0:
        reason_text = f" {reason}" if reason else ""
        raise AssertionError(
            f"Expected {label} >= {minimum_version}, found {actual_version}.{reason_text}"
        )
    return actual_version


def assert_app_version_at_least(minimum_version, repo_root=None, reason=None):
    """Assert that the current app VERSION is at least the feature implementation version."""
    app_version = read_app_version(repo_root)
    return assert_version_at_least(
        app_version,
        minimum_version,
        label="config.py VERSION",
        reason=reason,
    )
