#!/usr/bin/env python3
# test_logo_upload_storage_resolution.py
"""
Functional regression test for home page logo upload storage quality.

Version: 0.261.038
Implemented in: 0.241.059

This test ensures that uploaded logos are no longer reduced to 100px tall
before storage. Instead, the admin upload pipeline preserves enough
resolution for the home page logo control while capping stored height at
500px to keep settings payloads bounded.

The conversion helpers moved to ``functions_branding_images.py`` in 0.261.038
so the V2 admin surface could accept the same uploads without a second
implementation, so the source assertions follow them there.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.templates import read_admin_settings_template


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(REPO_ROOT, "application", "single_app", "route_frontend_admin_settings.py")
BRANDING_IMAGES_FILE = os.path.join(
    REPO_ROOT, "application", "single_app", "functions_branding_images.py"
)


def test_logo_storage_helper_exists():
    """The shared branding module should define the helper and 500px storage cap."""
    print("Testing shared helper for logo storage quality...")
    errors = []

    with open(BRANDING_IMAGES_FILE, encoding="utf-8") as handle:
        content = handle.read()

    if "MAX_CUSTOM_LOGO_STORAGE_HEIGHT = 500" not in content:
        errors.append("MAX_CUSTOM_LOGO_STORAGE_HEIGHT = 500 not found in functions_branding_images.py")

    if "def prepare_logo_image_for_storage" not in content:
        errors.append("prepare_logo_image_for_storage helper not found in functions_branding_images.py")

    if "img.save(img_bytes_io, format='PNG', optimize=True)" not in content:
        errors.append("Logo storage helper does not save optimized PNG output")

    with open(ROUTE_FILE, encoding="utf-8") as handle:
        route_content = handle.read()

    # Both admin surfaces must share one conversion, or a logo would be stored
    # at a different size depending on where it was uploaded from.
    if "from functions_branding_images import" not in route_content:
        errors.append("route_frontend_admin_settings.py does not import the shared branding helpers")

    return _summarise(errors, "shared helper existence")


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
    """Admin branding UI should explain the higher-resolution storage behavior.

    The branding controls live in ``templates/admin/_panes/branding.html``, so
    the parent template has to be composed before the help text is visible.
    """
    print("\nTesting admin branding help text for logo storage cap...")
    errors = []

    content = read_admin_settings_template()

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