# test_route_backend_models_safe_logging.py
#!/usr/bin/env python3
"""
Functional test for safe route backend model logging and error responses.
Version: 0.239.190
Implemented in: 0.239.190

This test ensures route_backend_models.py uses log_event-based logging and
does not return raw exception text directly to the browser.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_route_backend_models_uses_safe_logging_and_errors():
    """Ensure route_backend_models.py logs through log_event and avoids raw exception responses."""
    print("🔍 Validating safe logging and user-facing model route errors...")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    backend_path = os.path.join(repo_root, "application", "single_app", "route_backend_models.py")
    backend_content = read_file_text(backend_path)

    assert "from functions_appinsights import log_event" in backend_content, (
        "route_backend_models.py must import log_event for route logging."
    )
    assert "from functions_debug import debug_print" not in backend_content, (
        "route_backend_models.py should no longer depend on debug_print for logging."
    )
    assert "def log_models_debug(" in backend_content, (
        "route_backend_models.py should centralize debug logging through log_event."
    )
    assert "return jsonify({\"error\": str(e)})" not in backend_content, (
        "route_backend_models.py must not return raw exception text to the browser."
    )
    assert "return jsonify({\"error\": str(exc)})" not in backend_content, (
        "route_backend_models.py must not return raw exception text from handled exceptions."
    )
    assert "def build_group_access_error_response(" in backend_content, (
        "route_backend_models.py should map group access failures to safe user messages."
    )

    print("✅ Safe logging and user-facing error handling verified.")


if __name__ == "__main__":
    test_route_backend_models_uses_safe_logging_and_errors()