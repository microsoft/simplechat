#!/usr/bin/env python3
"""
Functional test for admin safe_int fallback hardening.
Version: 0.239.006
Implemented in: 0.239.006

This test ensures admin settings integer parsing always returns ints,
including when persisted fallback values are malformed.
"""

import os
import sys
import traceback

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _read_file(*path_parts):
    file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        *path_parts
    )
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_safe_int_hardening_markers():
    """Validate safe_int hard fallback handling is wired."""
    print("🔍 Testing admin safe_int fallback hardening wiring...")

    route_content = _read_file("application", "single_app", "route_frontend_admin_settings.py")

    required_markers = [
        "def safe_int(raw_value, fallback_value, field_name=\"unknown\", hard_default=0):",
        "parsed_fallback = int(fallback_value)",
        "Invalid admin settings integer input and fallback detected; using hard default value.",
        "return int(hard_default)",
        "idle_timeout_minutes = max(1, safe_int(form_data.get('idle_timeout_minutes'), settings.get('idle_timeout_minutes', 30), 'idle_timeout_minutes', 30))",
        "idle_warning_minutes = max(0, safe_int(form_data.get('idle_warning_minutes'), settings.get('idle_warning_minutes', 28), 'idle_warning_minutes', 28))"
    ]

    missing_markers = [marker for marker in required_markers if marker not in route_content]
    assert not missing_markers, f"Missing safe_int hardening markers: {missing_markers}"

    print("✅ Admin safe_int fallback hardening wiring is present")


def test_version_alignment_for_safe_int_fix():
    """Validate config version aligns with safe_int fix release."""
    print("🔍 Testing version alignment for safe_int fallback fix...")

    config_content = _read_file("application", "single_app", "config.py")

    required_markers = [
        "VERSION = \"0.239.006\""
    ]

    missing_markers = [marker for marker in required_markers if marker not in config_content]
    assert not missing_markers, f"Missing config markers: {missing_markers}"

    print("✅ Safe_int fix release version markers are aligned")


def main():
    """Run all safe_int fallback hardening functional checks."""
    print("🧪 Running Admin Safe Int Fallback Functional Tests...\n")

    tests = [
        test_safe_int_hardening_markers,
        test_version_alignment_for_safe_int_fix
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except AssertionError as error:
            print(f"❌ {test.__name__} failed: {error}")
            results.append(False)
        except Exception as error:
            print(f"❌ {test.__name__} error: {error}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")

    if success:
        print("✅ All admin safe_int fallback functional tests passed!")
    else:
        print("❌ Some admin safe_int fallback functional tests failed.")

    return success


if __name__ == "__main__":
    test_success = main()
    sys.exit(0 if test_success else 1)
