#!/usr/bin/env python3
# test_logo_upload_storage_resolution.py
"""
Functional regression test for home page logo upload storage quality.

Version: 0.241.059
Implemented in: 0.241.059

This test ensures that uploaded logos are no longer reduced to 100px tall
before storage. Instead, the admin upload pipeline preserves enough
resolution for the home page logo control while capping stored height at
500px to keep settings payloads bounded.
"""

import os
import re
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(REPO_ROOT, "application", "single_app", "route_frontend_admin_settings.py")
ADMIN_TEMPLATE = os.path.join(REPO_ROOT, "application", "single_app", "templates", "admin_settings.html")


def test_logo_storage_helper_exists():
    """Route file should define a dedicated helper and 500px storage cap."""
    print("Testing route helper for logo storage quality...")
    errors = []

    with open(ROUTE_FILE, encoding="utf-8") as handle:
        content = handle.read()

    if "MAX_CUSTOM_LOGO_STORAGE_HEIGHT = 500" not in content:
        errors.append("MAX_CUSTOM_LOGO_STORAGE_HEIGHT = 500 not found in route_frontend_admin_settings.py")

    if "def prepare_logo_image_for_storage" not in content:
        errors.append("prepare_logo_image_for_storage helper not found in route_frontend_admin_settings.py")

    if "img.save(img_bytes_io, format='PNG', optimize=True)" not in content:
        errors.append("Logo storage helper does not save optimized PNG output")

    return _summarise(errors, "route helper existence")


def test_logo_upload_no_longer_forces_100px_height():
    """Route file should no longer rescale custom logos to 100px tall."""
    print("\nTesting that logo upload no longer hard-resizes to 100px...")
    errors = []

    with open(ROUTE_FILE, encoding="utf-8") as handle:
        content = handle.read()

    forbidden_patterns = [
        r"Resize to height=100",
        r"new_height\s*=\s*100",
        r"if\s+h\s*>\s*100",
    ]

    for pattern in forbidden_patterns:
        if re.search(pattern, content):
            errors.append(f"Found legacy 100px logo resize pattern: {pattern}")

    if "prepare_logo_image_for_storage(file_bytes, logo_file.filename)" not in content:
        errors.append("Light logo upload path does not use prepare_logo_image_for_storage")

    if "prepare_logo_image_for_storage(file_bytes, logo_dark_file.filename)" not in content:
        errors.append("Dark logo upload path does not use prepare_logo_image_for_storage")

    return _summarise(errors, "legacy 100px resize removal")


def test_admin_template_documents_500px_storage_cap():
    """Admin branding UI should explain the higher-resolution storage behavior."""
    print("\nTesting admin branding help text for logo storage cap...")
    errors = []

    with open(ADMIN_TEMPLATE, encoding="utf-8") as handle:
        content = handle.read()

    if "stored at up to 500px tall" not in content:
        errors.append("Admin settings help text does not mention the 500px logo storage cap")

    return _summarise(errors, "admin template help text")


def _summarise(errors, label):
    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        return False
    print(f"  All {label} checks passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_logo_storage_helper_exists,
        test_logo_upload_no_longer_forces_100px_height,
        test_admin_template_documents_500px_storage_cap,
    ]
    results = []
    for test in tests:
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)