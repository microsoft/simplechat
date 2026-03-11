#!/usr/bin/env python3
"""
Functional test for settings deep-merge persistence fix.
Version: 0.239.006
Implemented in: 0.239.006

This test ensures get_settings compares merged settings against a pre-merge deep copy
so missing default keys are persisted back to Cosmos DB.
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


def test_merge_detection_uses_pre_merge_snapshot():
    """Validate deep-copy comparison markers exist in settings merge path."""
    print("🔍 Testing settings merge persistence detection wiring...")

    settings_content = _read_file("application", "single_app", "functions_settings.py")

    required_markers = [
        "import copy",
        "original_settings_item = copy.deepcopy(settings_item)",
        "merged = deep_merge_dicts(default_settings, settings_item)",
        "if merged != original_settings_item:",
        "cosmos_settings_container.upsert_item(merged)",
        "App settings missing keys were merged and persisted to Cosmos DB."
    ]

    missing_markers = [marker for marker in required_markers if marker not in settings_content]
    assert not missing_markers, f"Missing merge persistence markers in functions_settings.py: {missing_markers}"

    print("✅ Settings merge persistence detection wiring is present")


def test_version_alignment_for_fix_release():
    """Validate config version reflects this fix release."""
    print("🔍 Testing fix release version alignment...")

    config_content = _read_file("application", "single_app", "config.py")

    required_markers = [
        "VERSION = \"0.239.006\""
    ]

    missing_markers = [marker for marker in required_markers if marker not in config_content]
    assert not missing_markers, f"Missing config markers: {missing_markers}"

    print("✅ Fix release version markers are aligned")


def main():
    """Run all functional checks for deep-merge persistence fix."""
    print("🧪 Running Settings Deep Merge Persistence Functional Tests...\n")

    tests = [
        test_merge_detection_uses_pre_merge_snapshot,
        test_version_alignment_for_fix_release
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
        print("✅ All deep-merge persistence functional tests passed!")
    else:
        print("❌ Some deep-merge persistence functional tests failed.")

    return success


if __name__ == "__main__":
    test_success = main()
    sys.exit(0 if test_success else 1)
