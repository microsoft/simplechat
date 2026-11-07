# test_csrf_state_changing_route_guard.py
"""
Functional test for CSRF state-changing route guard.
Version: 0.242.072
Implemented in: 0.242.053
Updated in: 0.242.072

This test ensures authenticated unsafe-method Flask requests have a same-origin
browser boundary, the Teams token exchange has a pre-session same-origin
boundary, and session-cookie defaults are explicit.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_FILE = REPO_ROOT / "application" / "single_app" / "app.py"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


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
        "_origin_matches_allowed_origin",
        "_origin_matches_any_allowed_origin",
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
        "request.path == '/auth/teams/token-exchange' and ENABLE_TEAMS_SSO",
        "if 'user' not in session and not is_teams_token_exchange:",
        "return jsonify({",
        "}), 403",
    ]
    missing_snippets = [snippet for snippet in required_snippets if snippet not in app_source]
    assert not missing_snippets, f"Missing CSRF guard snippets: {missing_snippets}"

    cross_site_index = app_source.index("if fetch_site == 'cross-site':")
    same_origin_index = app_source.index("if fetch_site == 'same-origin':")
    origin_compare_index = app_source.index("allowed_origins = _build_allowed_request_origins()")
    assert cross_site_index < same_origin_index < origin_compare_index


def test_cross_site_requests_require_an_explicitly_trusted_origin():
    """Cross-site mutations are refused unless the Origin is on the trusted allowlist.

    A separately hosted front end (the standalone V2 UI app service) is cross-site by
    definition, so the guard consults the allowlist before refusing. This must not become
    a blanket allowance: the branch has to check the Origin header against
    _build_allowed_request_origins and still return False when it does not match.
    """
    app_source = _read_text(APP_FILE)

    cross_site_start = app_source.index("if fetch_site == 'cross-site':")
    cross_site_block = app_source[cross_site_start : app_source.index("if fetch_site == 'same-origin':")]

    assert "_origin_matches_any_allowed_origin(" in cross_site_block, (
        "The cross-site branch must validate the Origin against the trusted allowlist"
    )
    assert "_build_allowed_request_origins()" in cross_site_block, (
        "The cross-site branch must build the allowed origin set before trusting a request"
    )
    assert "return False, 'cross-site fetch metadata'" in cross_site_block, (
        "A cross-site request whose Origin is not trusted must still be refused"
    )


def test_cors_preflight_is_answered_before_authentication():
    """CORS preflights are answered ahead of the auth guards and never wildcard.

    Preflights carry no cookies, so if they reached the blueprint auth guard they would be
    rejected with 401 and every cross-origin mutation would fail. The handler must also be
    inert unless V2_UI_ALLOWED_ORIGINS is configured.
    """
    app_source = _read_text(APP_FILE)
    app_tree = ast.parse(app_source)

    function_names = {
        node.name for node in ast.walk(app_tree) if isinstance(node, ast.FunctionDef)
    }
    assert "answer_cors_preflight_for_allowed_origins" in function_names, (
        "The CORS preflight handler is missing"
    )

    handler_start = app_source.index("def answer_cors_preflight_for_allowed_origins():")
    handler_block = app_source[
        handler_start : app_source.index("def enforce_same_origin_for_state_changing_requests():")
    ]

    assert "if not V2_UI_ALLOWED_ORIGINS or request.method != 'OPTIONS':" in handler_block, (
        "The preflight handler must be inert when no separate UI origin is configured"
    )
    assert "Access-Control-Request-Method" in handler_block, (
        "The handler must only answer genuine preflights"
    )
    assert "request_origin not in V2_UI_ALLOWED_ORIGINS" in handler_block, (
        "The handler must only answer for an exactly allowlisted origin"
    )
    assert "'*'" not in handler_block, (
        "A wildcard origin is incompatible with Allow-Credentials and must never be emitted"
    )

    # It must be registered as an app-level before_request, which Flask runs ahead of
    # blueprint guards.
    preflight_decorator_index = app_source.index(
        "@app.before_request\ndef answer_cors_preflight_for_allowed_origins():"
    )
    assert preflight_decorator_index > 0, (
        "The preflight handler must be an app-level @app.before_request"
    )


def test_session_cookie_defaults_are_explicit():
    """Validate session cookies have explicit SameSite/HttpOnly defaults."""
    config_source = _read_text(CONFIG_FILE)
    app_source = _read_text(APP_FILE)

    config_required = [
        "SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')",
        "SESSION_COOKIE_HTTPONLY = os.getenv('SESSION_COOKIE_HTTPONLY', 'true').lower() != 'false'",
        "SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'",
        "CSRF_ENFORCE_ORIGIN_FOR_UNSAFE_METHODS = os.getenv(",
        "CSRF_TRUSTED_ORIGINS = _split_origin_list(",
    ]
    missing_config = [snippet for snippet in config_required if snippet not in config_source]
    assert not missing_config, f"Missing config snippets: {missing_config}"

    # The version is checked as a lower bound rather than an exact literal, so a routine
    # version bump does not fail this test.
    assert_app_version_at_least("0.242.072")

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
        test_cross_site_requests_require_an_explicitly_trusted_origin,
        test_cors_preflight_is_answered_before_authentication,
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