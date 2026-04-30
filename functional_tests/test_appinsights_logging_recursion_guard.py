#!/usr/bin/env python3
"""
Functional test for Application Insights logging recursion guard.
Version: 0.240.005
Implemented in: 0.240.005

This test ensures _load_logging_settings uses a re-entrancy guard to avoid
recursive get_settings() -> log_event() -> _load_logging_settings() loops.
"""

import os
import re
import sys


def test_recursion_guard_present():
    """Validate recursion guard markers exist in functions_appinsights.py."""
    print("🔍 Testing Application Insights logging recursion guard...")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_path = os.path.join(repo_root, 'application', 'single_app', 'functions_appinsights.py')

    try:
        with open(target_path, 'r', encoding='utf-8') as file_handle:
            content = file_handle.read()

        assert "_logging_settings_load_state = threading.local()" in content, (
            "Missing thread-local guard state declaration"
        )

        function_match = re.search(
            r"def _load_logging_settings\(\) -> Dict\[str, Any\]:(.*?)(?:\ndef\s+_emit_debug_message|\Z)",
            content,
            re.DOTALL,
        )
        assert function_match, "Could not locate _load_logging_settings function body"
        function_body = function_match.group(1)

        assert "getattr(_logging_settings_load_state, 'active', False)" in function_body, (
            "Missing guard check for active re-entrancy"
        )
        assert "_logging_settings_load_state.active = True" in function_body, (
            "Missing guard activation before get_settings call"
        )
        assert "finally:" in function_body and "_logging_settings_load_state.active = False" in function_body, (
            "Missing guard reset in finally block"
        )

        print("✅ Recursion guard checks passed")
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
    success = test_recursion_guard_present()
    sys.exit(0 if success else 1)
