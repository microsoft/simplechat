#!/usr/bin/env python3
"""
Functional test for startup custom logo file preservation.
Version: 0.240.004
Implemented in: 0.240.004

This test ensures that app startup does not delete existing custom logo files
when custom logo base64 settings are empty.
"""

import os
import re
import sys


def test_logo_preservation_logic_in_config():
    """Validate that ensure_custom_logo_file_exists preserves files when base64 values are empty."""
    print("🔍 Testing custom logo preservation logic in config.py...")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(repo_root, 'application', 'single_app', 'config.py')

    try:
        with open(config_path, 'r', encoding='utf-8') as config_file:
            content = config_file.read()

        function_match = re.search(
            r"def ensure_custom_logo_file_exists\(app, settings\):(.*?)(?:\ndef\s+ensure_custom_favicon_file_exists|\Z)",
            content,
            re.DOTALL,
        )

        assert function_match, "Could not find ensure_custom_logo_file_exists in config.py"
        function_body = function_match.group(1)

        assert "Preserving existing {logo_filename}" in function_body, (
            "Expected preserve behavior message for light logo not found"
        )
        assert "Preserving existing {logo_dark_filename}" in function_body, (
            "Expected preserve behavior message for dark logo not found"
        )
        assert "os.remove(logo_path)" not in function_body, (
            "Light logo should not be removed when base64 is empty"
        )
        assert "os.remove(logo_dark_path)" not in function_body, (
            "Dark logo should not be removed when base64 is empty"
        )

        print("✅ Startup logo preservation checks passed")
        return True

    except AssertionError as assertion_error:
        print(f"❌ Assertion failed: {assertion_error}")
        return False
    except Exception as ex:
        print(f"❌ Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    passed = test_logo_preservation_logic_in_config()
    sys.exit(0 if passed else 1)
