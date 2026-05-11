#!/usr/bin/env python3
"""
Functional test for get_settings deep-merge bool regression.
Version: 0.240.006
Implemented in: 0.240.006

This test ensures get_settings treats deep_merge_dicts() return as a change flag
and continues using the settings dictionary for migrations and persistence.
"""

import os
import re
import sys


def test_get_settings_uses_merge_changed_flag():
    """Validate the get_settings merge logic does not treat deep_merge_dicts return as settings dict."""
    print("🔍 Testing get_settings deep merge regression markers...")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_path = os.path.join(repo_root, 'application', 'single_app', 'functions_settings.py')

    try:
        with open(target_path, 'r', encoding='utf-8') as file_handle:
            content = file_handle.read()

        assert "merge_changed = deep_merge_dicts(default_settings, settings_item)" in content, (
            "Expected merge_changed assignment not found"
        )
        assert "merged = settings_item" in content, (
            "Expected merged dict assignment not found"
        )
        assert "if merge_changed or migration_updated:" in content, (
            "Expected merge change flag check not found"
        )

        old_pattern = re.compile(r"merged\s*=\s*deep_merge_dicts\(default_settings,\s*settings_item\)")
        assert not old_pattern.search(content), (
            "Found legacy assignment that treats deep_merge_dicts return as merged dict"
        )

        print("✅ get_settings merge regression checks passed")
        return True

    except AssertionError as assertion_error:
        print(f"❌ Assertion failed: {assertion_error}")
        return False
    except Exception as ex:
        print(f"❌ Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_get_settings_uses_merge_changed_flag()
    sys.exit(0 if success else 1)
