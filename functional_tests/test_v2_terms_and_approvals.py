#!/usr/bin/env python3
# test_v2_terms_and_approvals.py
"""
Functional test for the V2 Terms of Use page and the V2 Approval requests page.
Version: 0.261.277
Implemented in: 0.261.277

This test ensures the Terms of Use gate sends V2 requests to the V2 page, the V2 terms
endpoints exist with the required decorators and are exempt from the gate, the approvals
rail preference is writable, and the V2 approvals page is wired to every request kind the
classic page serves.
"""

import ast
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"


def _read(path):
    return path.read_text(encoding="utf-8")


def _load_app_functions(*names):
    """Compile only the named top-level helpers from app.py, without importing the app."""
    source = _read(APP_DIR / "app.py")
    tree = ast.parse(source)
    wanted = set(names)
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in wanted for target in node.targets
        ):
            nodes.append(node)
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {
        "urlencode": urlencode,
        "url_for": lambda endpoint, **kwargs: f"/terms-of-use?{urlencode(kwargs)}",
    }
    exec(compile(module, "app_helpers", "exec"), namespace)  # noqa: S102 - trusted repo source
    return namespace


def test_gate_sends_v2_requests_to_the_v2_page():
    """V2 pages keep their location as next; V2 API calls get the bare V2 page."""
    helpers = _load_app_functions(
        "V2_TERMS_OF_USE_PATH",
        "_is_v2_request_path",
        "normalize_path_with_query",
        "build_terms_of_use_url",
    )
    build = helpers["build_terms_of_use_url"]

    page_url = build("/v2/workspace/documents", b"tab=mine")
    parsed = urlparse(page_url)
    assert parsed.path == "/v2/terms-of-use", page_url
    assert parse_qs(parsed.query) == {"next": ["/v2/workspace/documents?tab=mine"]}, page_url

    assert build("/api/v2/bootstrap", b"") == "/v2/terms-of-use"
    assert build("/v2", b"").startswith("/v2/terms-of-use?")

    classic = build("/chats", b"")
    assert classic.startswith("/terms-of-use?"), classic
    # A path that merely starts with the letters is not a V2 path.
    assert build("/v2x", b"").startswith("/terms-of-use?")
    print("PASS: the gate routes V2 and classic requests to their own page")


def test_v2_terms_paths_are_exempt_from_the_gate():
    source = _read(APP_DIR / "app.py")
    for path in (
        "'/v2/terms-of-use'",
        "'/api/v2/terms-of-use'",
        "'/api/v2/terms-of-use/accept'",
        "'/api/v2/terms-of-use/decline'",
    ):
        assert path in source, f"{path} should be exempt from the Terms of Use gate"
    assert "terms_url = build_terms_of_use_url(request.path, request.query_string)" in source
    print("PASS: the V2 terms paths are exempt")


def test_v2_terms_routes_have_required_decorators():
    tree = ast.parse(_read(APP_DIR / "route_backend_v2.py"))
    expected = {
        "v2_terms_of_use": ("/api/v2/terms-of-use", "GET"),
        "v2_accept_terms_of_use": ("/api/v2/terms-of-use/accept", "POST"),
        "v2_decline_terms_of_use": ("/api/v2/terms-of-use/decline", "POST"),
    }
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in expected:
            decorators = [ast.unparse(item) for item in node.decorator_list]
            found[node.name] = decorators
    assert set(found) == set(expected), f"missing V2 terms routes: {set(expected) - set(found)}"
    for name, (path, method) in expected.items():
        decorators = found[name]
        assert decorators[0] == f"bp.route('{path}', methods=['{method}'])", decorators
        assert decorators[1] == "swagger_route(security=get_auth_security())", decorators
        assert "login_required" in decorators and "user_required" in decorators, decorators
    print("PASS: the V2 terms routes carry swagger and auth decorators")


def test_v2_terms_frontend_is_wired():
    app_tsx = _read(V2_SRC / "App.tsx")
    assert "TermsOfUsePage" in app_tsx
    assert "/terms-of-use" in app_tsx
    api_client = _read(V2_SRC / "lib" / "apiClient.ts")
    assert "terms" in api_client.lower()
    page = _read(V2_SRC / "pages" / "TermsOfUsePage.tsx")
    assert "dangerouslySetInnerHTML" not in page
    print("PASS: the V2 terms page is routed and renders text only")


def test_approvals_rail_preference_is_writable():
    users_route = _read(APP_DIR / "route_backend_users.py")
    assert "'v2ApprovalsRailCollapsed'" in users_route or '"v2ApprovalsRailCollapsed"' in users_route
    user_settings = _read(V2_SRC / "lib" / "userSettings.ts")
    assert user_settings.count("v2ApprovalsRailCollapsed") >= 2
    print("PASS: the approvals rail preference is writable")


def test_v2_approvals_page_covers_every_request_kind():
    app_tsx = _read(V2_SRC / "App.tsx")
    for route in ('path="/approvals"', 'path="/approvals/:category"', 'path="/approvals/:category/:itemId"'):
        assert route in app_tsx, route

    page = _read(V2_SRC / "pages" / "ApprovalsPage.tsx")
    for category in ("'all'", "'group'", "'m365'", "'content-screening'", "'outgoing'", "'paused'", "'agent-templates'"):
        assert f"id: {category}" in page, category
    for panel in ("GenericApprovalsPanel", "PendingActionsPanel", "PausedRequestsPanel", "AgentTemplatesPanel"):
        assert panel in page, panel
    # Agent templates are for administrators only; content screening follows its feature.
    assert "if (isAdmin)" in page
    assert "enable_content_screening" in page
    # Classic-style links still resolve.
    for deep_link in ("m365_approval", "approval_id", "#agent-template-approvals"):
        assert deep_link in page, deep_link

    components = V2_SRC / "components" / "approvals"
    for component in components.glob("*.tsx"):
        assert "dangerouslySetInnerHTML" not in _read(component), component.name

    api = _read(V2_SRC / "lib" / "approvalsApi.ts")
    for endpoint in (
        "/api/approvals",
        "/api/m365/approvals/",
        "/api/m365/requests",
        "/api/msgraph/pending-actions",
        "/api/admin/agent-templates",
    ):
        assert endpoint in api, endpoint
    print("PASS: the V2 approvals page covers every request kind")


def test_v2_navigation_points_at_the_v2_approvals_page():
    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    assert "to: '/approvals'" in sidebar
    links = _read(V2_SRC / "lib" / "notificationLinks.ts")
    assert "return route(`/approvals${url.search}${url.hash}`);" in links
    template_link = _read(V2_SRC / "components" / "admin" / "AgentTemplateApprovalsLink.tsx")
    assert 'to="/approvals/agent-templates"' in template_link
    print("PASS: V2 navigation opens the V2 approvals page")


def test_version():
    assert_app_version_at_least("0.261.277")
    print("PASS: version is at least 0.261.277")


if __name__ == "__main__":
    tests = [
        test_gate_sends_v2_requests_to_the_v2_page,
        test_v2_terms_paths_are_exempt_from_the_gate,
        test_v2_terms_routes_have_required_decorators,
        test_v2_terms_frontend_is_wired,
        test_approvals_rail_preference_is_writable,
        test_v2_approvals_page_covers_every_request_kind,
        test_v2_navigation_points_at_the_v2_approvals_page,
        test_version,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
