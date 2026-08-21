#!/usr/bin/env python3
# test_plugin_error_response_sanitization.py
"""
Functional test for plugin error response sanitization.
Version: 0.250.124
Implemented in: 0.250.124

This test ensures PR security-review fixes keep raw exception text out of
client-visible plugin/action error responses and external telemetry log messages.
"""

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_plugins.py"
APPINSIGHTS_FILE = REPO_ROOT / "application" / "single_app" / "functions_appinsights.py"
INSTRUCTIONS_FILE = REPO_ROOT / ".github" / "instructions" / "python-lang.instructions.md"


def _read(path):
    return path.read_text(encoding="utf-8")


def test_key_vault_plugin_exception_responses_are_stable():
    """Validate newly added Key Vault/plugin exception paths return safe messages."""
    print("Testing plugin Key Vault exception response sanitization...")
    route_source = _read(ROUTE_FILE)

    required_safe_messages = (
        "ACTION_VALIDATION_ERROR_MESSAGE",
        "ACTION_PERMISSION_ERROR_MESSAGE",
        "ACTION_KEY_VAULT_ERROR_MESSAGE",
        "PLUGIN_VALIDATION_ERROR_MESSAGE",
        "PLUGIN_KEY_VAULT_ERROR_MESSAGE",
    )
    for message_name in required_safe_messages:
        assert message_name in route_source, f"Missing safe response constant {message_name}"

    forbidden_blocks = (
        r"except RuntimeError as e:\s+debug_print\(f\"Key Vault error saving personal actions.*?"
        r"return jsonify\(\{'error': str\(e\)\}\), 500",
        r"except ValueError as exc:\s+return jsonify\(\{'error': str\(exc\)\}\), 400\s+"
        r"except PermissionError as exc:\s+return jsonify\(\{'error': str\(exc\)\}\), 403\s+"
        r"except RuntimeError as exc:\s+debug_print\('Key Vault error saving group action.*?"
        r"return jsonify\(\{'error': str\(exc\)\}\), 500",
        r"except ValueError as exc:\s+return jsonify\(\{'error': str\(exc\)\}\), 400\s+"
        r"except PermissionError as exc:\s+return jsonify\(\{'error': str\(exc\)\}\), 403\s+"
        r"except RuntimeError as exc:\s+debug_print\('Key Vault error updating group action.*?"
        r"return jsonify\(\{'error': str\(exc\)\}\), 500",
        r"except ValueError as e:\s+log_event\(f\"Validation error adding plugin.*?"
        r"return jsonify\(\{'error': str\(e\)\}\), 400\s+"
        r"except RuntimeError as e:\s+log_event\(f\"Key Vault error adding plugin.*?"
        r"return jsonify\(\{'error': str\(e\)\}\), 500",
        r"except ValueError as e:\s+log_event\(f\"Validation error editing plugin.*?"
        r"return jsonify\(\{'error': str\(e\)\}\), 400\s+"
        r"except RuntimeError as e:\s+log_event\(f\"Key Vault error editing plugin.*?"
        r"return jsonify\(\{'error': str\(e\)\}\), 500",
    )
    for forbidden_pattern in forbidden_blocks:
        assert not re.search(forbidden_pattern, route_source, re.DOTALL), (
            "Raw exception text is still returned from a Key Vault/plugin exception path"
        )

    print("Test passed!")
    return True


def test_external_telemetry_event_name_avoids_secret_word_in_logger_message():
    """Validate external telemetry does not log the event name as message text."""
    print("Testing external telemetry logger message hardening...")
    appinsights_source = _read(APPINSIGHTS_FILE)
    assert "event_message = f\"{LOGGER_EXTERNAL_EVENT_MESSAGE}" not in appinsights_source
    assert "LOGGER_EXTERNAL_EVENT_MESSAGE," in appinsights_source

    reminder_source = _read(REPO_ROOT / "application" / "single_app" / "functions_keyvault_reminders.py")
    assert 'KEY_VAULT_REMINDER_EXTERNAL_EVENT_NAME = "key_vault_expiration_reminder_triggered"' in reminder_source

    print("Test passed!")
    return True


def test_python_instructions_ban_raw_exception_responses():
    """Validate the repo instructions prevent future raw exception responses."""
    print("Testing Python instruction coverage for raw exception responses...")
    instructions_source = _read(INSTRUCTIONS_FILE)
    assert "Never return raw exception text" in instructions_source
    assert "str(e)" in instructions_source
    assert "str(exc)" in instructions_source
    assert "repr(e)" in instructions_source

    print("Test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_key_vault_plugin_exception_responses_are_stable,
        test_external_telemetry_event_name_avoids_secret_word_in_logger_message,
        test_python_instructions_ban_raw_exception_responses,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {type(exc).__name__}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
