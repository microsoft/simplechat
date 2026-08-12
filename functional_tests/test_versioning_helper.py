#!/usr/bin/env python3
# test_versioning_helper.py
"""
Functional test for shared test version helpers.
Version: 0.250.126
Implemented in: 0.250.126

This test ensures functional tests can validate minimum application versions
without failing after later config.py VERSION bumps.
"""

import sys

from test_support.versioning import (
    assert_app_version_at_least,
    assert_version_at_least,
    compare_simplechat_versions,
    parse_simplechat_version,
    read_app_version,
)


def test_parse_and_compare_simplechat_versions():
    """Validate dotted numeric version parsing and comparison."""
    print("Testing SimpleChat version parsing and comparison...")

    assert parse_simplechat_version("0.250.125") == (0, 250, 125)
    assert parse_simplechat_version("v0.250.125") == (0, 250, 125)
    assert compare_simplechat_versions("0.250.125", "0.250.124") == 1
    assert compare_simplechat_versions("0.250.125", "0.250.125") == 0
    assert compare_simplechat_versions("0.250.124", "0.250.125") == -1
    assert compare_simplechat_versions("0.250", "0.250.000") == 0

    try:
        parse_simplechat_version("0.250.beta")
    except AssertionError:
        pass
    else:
        raise AssertionError("Invalid nonnumeric versions should fail parsing.")

    print("Version parsing and comparison passed.")
    return True


def test_version_at_least_assertions():
    """Validate reusable >= assertion helpers."""
    print("Testing version >= assertions...")

    assert assert_version_at_least("0.250.125", "0.250.124") == "0.250.125"
    assert assert_version_at_least("0.250.125", "0.250.125") == "0.250.125"

    try:
        assert_version_at_least("0.250.124", "0.250.125", label="test version")
    except AssertionError as ex:
        assert "Expected test version >= 0.250.125" in str(ex)
    else:
        raise AssertionError("Lower versions should fail the >= assertion.")

    current_version = read_app_version()
    assert assert_app_version_at_least("0.0.001") == current_version

    print("Version >= assertions passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_parse_and_compare_simplechat_versions,
        test_version_at_least_assertions,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as ex:
            print(f"Test failed: {ex}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
