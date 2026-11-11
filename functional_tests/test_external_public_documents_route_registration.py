#!/usr/bin/env python3
# test_external_public_documents_route_registration.py
"""
Functional test for external public document route registration.
Version: 0.261.062
Implemented in: 0.261.062

This test ensures the bearer-token protected external public document routes
and the access token preflight route are registered, so external bulk-loading
clients keep working.
"""

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
APP_FILE = APP_DIR / "app.py"
HEALTH_FILE = APP_DIR / "route_external_health.py"
PUBLIC_DOCS_FILE = APP_DIR / "route_external_public_documents.py"

BEARER_PROTECTED_ROUTES = [
    ("/external/public_documents", "GET"),
    ("/external/public_documents/upload", "POST"),
    ("/external/public_documents/<document_id>", "DELETE"),
]


def read_text(path: Path) -> str:
    """Return UTF-8 text for a repo file."""
    return path.read_text(encoding="utf-8")


def route_block(content: str, path: str, method: str) -> str:
    """Return the decorator and signature lines for one route."""
    pattern = re.compile(
        r"@bp\.route\('" + re.escape(path) + r"', methods=\['" + method + r"'\]\)(.*?)\n\s*def ",
        re.S,
    )
    match = pattern.search(content)
    if not match:
        raise AssertionError(f"Route {method} {path} not found")
    return match.group(1)


def test_app_registers_external_public_documents() -> bool:
    """Validate app.py imports and registers the external public document routes."""
    print("Testing external public document registration in app.py...")

    try:
        app_content = read_text(APP_FILE)
        required_snippets = [
            "from route_external_public_documents import *",
            "register_route_blueprint('external_public_documents', register_route_external_public_documents)",
        ]
        for snippet in required_snippets:
            if snippet not in app_content:
                raise AssertionError(f"Missing in app.py: {snippet}")

        print("Passed")
        return True
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


def test_external_routes_require_bearer_token() -> bool:
    """Validate the preflight and document routes use the bearer-token decorator."""
    print("Testing bearer-token protection on external routes...")

    try:
        health_content = read_text(HEALTH_FILE)
        docs_content = read_text(PUBLIC_DOCS_FILE)

        preflight = route_block(health_content, "/external/testaccesstoken", "POST")
        if "@accesstoken_required" not in preflight:
            raise AssertionError("/external/testaccesstoken must use @accesstoken_required")

        for path, method in BEARER_PROTECTED_ROUTES:
            block = route_block(docs_content, path, method)
            if "@accesstoken_required" not in block:
                raise AssertionError(f"{method} {path} must use @accesstoken_required")

        print("Passed")
        return True
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_app_registers_external_public_documents,
        test_external_routes_require_bearer_token,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
