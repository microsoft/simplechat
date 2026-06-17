# test_csrf_state_changing_route_guard.py
"""
Functional test for CSRF state-changing route guard.
Version: 0.242.053
Implemented in: 0.242.053

This test ensures authenticated unsafe-method Flask requests have a same-origin
browser boundary and explicit session-cookie defaults.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_FILE = REPO_ROOT / "application" / "single_app" / "app.py"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"


def _read_text(path):
    return path.read_text(encoding="utf-8")


def test_csrf_guard_structure():
    """Validate the global same-origin guard exists and blocks off-site mutations."""
    app_source = _read_text(APP_FILE)
    app_tree = ast.parse(app_source)
    function_names = {
        node.name
        for node in ast.walk(app_tree)
        if isinstance(node, ast.FunctionDef)
    }

    required_functions = {
        "_normalize_origin_from_url",
        "_build_allowed_request_origins",
        "_state_changing_request_has_same_origin_boundary",
        "enforce_same_origin_for_state_changing_requests",
    }
    missing_functions = required_functions - function_names
    assert not missing_functions, f"Missing CSRF guard functions: {sorted(missing_functions)}"

    required_snippets = [
        "UNSAFE_STATE_CHANGING_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}",
        "GET_STATE_CHANGING_PATH_PREFIXES = (",
        "'/api/chat/stream/reattach/'",
        "SAME_ORIGIN_FETCH_SITE_VALUES = {'same-origin', 'same-site', 'none'}",
        "def _requires_same_origin_state_change_boundary():",
        "request.headers.get('Sec-Fetch-Site'",
        "same-origin fetch metadata",
        "same-site fetch metadata without origin headers",
        "request.headers.get('Origin'",
        "request.headers.get('Referer'",
        "X-Forwarded-Host",
        "X-Forwarded-Proto",
        "CSRF_TRUSTED_ORIGINS",
        "front_door_url",
        "if 'user' not in session:",
        "return jsonify({",
        "}), 403",
    ]
    missing_snippets = [snippet for snippet in required_snippets if snippet not in app_source]
    assert not missing_snippets, f"Missing CSRF guard snippets: {missing_snippets}"

    cross_site_index = app_source.index("if fetch_site == 'cross-site':")
    same_origin_index = app_source.index("if fetch_site == 'same-origin':")
    origin_compare_index = app_source.index("allowed_origins = _build_allowed_request_origins()")
    assert cross_site_index < same_origin_index < origin_compare_index


def test_session_cookie_defaults_are_explicit():
    """Validate session cookies have explicit SameSite/HttpOnly defaults."""
    config_source = _read_text(CONFIG_FILE)
    app_source = _read_text(APP_FILE)

    config_required = [
        "VERSION = \"0.242.053\"",
        "SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')",
        "SESSION_COOKIE_HTTPONLY = os.getenv('SESSION_COOKIE_HTTPONLY', 'true').lower() != 'false'",
        "SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'",
        "CSRF_ENFORCE_ORIGIN_FOR_UNSAFE_METHODS = os.getenv(",
        "CSRF_TRUSTED_ORIGINS = [",
    ]
    missing_config = [snippet for snippet in config_required if snippet not in config_source]
    assert not missing_config, f"Missing config snippets: {missing_config}"

    app_required = [
        "app.config['SESSION_COOKIE_SAMESITE'] = SESSION_COOKIE_SAMESITE",
        "app.config['SESSION_COOKIE_HTTPONLY'] = SESSION_COOKIE_HTTPONLY",
        "app.config['SESSION_COOKIE_SECURE'] = SESSION_COOKIE_SECURE",
    ]
    missing_app = [snippet for snippet in app_required if snippet not in app_source]
    assert not missing_app, f"Missing app cookie snippets: {missing_app}"


if __name__ == "__main__":
    tests = [
        test_csrf_guard_structure,
        test_session_cookie_defaults_are_explicit,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"{test.__name__} passed")
            results.append(True)
        except Exception as exc:
            print(f"{test.__name__} failed: {exc}")
            results.append(False)

    success = all(results)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)