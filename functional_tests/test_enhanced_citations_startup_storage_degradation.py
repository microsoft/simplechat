# test_enhanced_citations_startup_storage_degradation.py
#!/usr/bin/env python3
"""
Functional test for Enhanced Citations startup storage degradation.
Version: 0.250.126
Implemented in: 0.250.126

This test ensures Enhanced Citations storage stays an optional dependency during
startup and that storage container readiness is handled by feature/admin paths.
"""

import ast
import sys
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "application" / "single_app" / "config.py"
FUNCTIONS_DOCUMENTS_PATH = REPO_ROOT / "application" / "single_app" / "functions_documents.py"
ROUTE_FRONTEND_ADMIN_SETTINGS_PATH = REPO_ROOT / "application" / "single_app" / "route_frontend_admin_settings.py"
ROUTE_BACKEND_SETTINGS_PATH = REPO_ROOT / "application" / "single_app" / "route_backend_settings.py"
ADMIN_SETTINGS_TEMPLATE_PATH = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
ADMIN_SETTINGS_JS_PATH = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"


def read_text(path):
    """Read a repository file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def get_function_source(path, function_name):
    """Return source text for a top-level function by using AST line numbers."""
    content = read_text(path)
    tree = ast.parse(content)
    lines = content.splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError(f"Function {function_name} was not found in {path}")


def test_startup_storage_initialization_is_non_blocking():
    """Verify startup setup does not probe or create Enhanced Citations containers."""
    print("Testing Enhanced Citations startup storage initialization...")

    startup_source = get_function_source(CONFIG_PATH, "_initialize_enhanced_citations_storage_client")

    assert_app_version_at_least(
        "0.250.126",
        repo_root=REPO_ROOT,
        reason="Enhanced Citations startup storage degradation fix requires this version or newer.",
    )
    if ".exists(" in startup_source:
        raise AssertionError("Startup initialization must not call container exists().")
    if "create_container" in startup_source:
        raise AssertionError("Startup initialization must not create storage containers.")
    if "build_enhanced_citations_blob_service_client(settings)" not in startup_source:
        raise AssertionError("Startup should only build the Enhanced Citations Blob client.")
    if "initialization_failed" not in startup_source:
        raise AssertionError("Startup initialization failures must be surfaced as degraded status.")
    if "except Exception as exc" not in startup_source:
        raise AssertionError("Optional storage client setup must not be able to fail app startup.")

    print("Startup initialization is non-blocking for Enhanced Citations storage.")


def test_upload_path_owns_container_readiness():
    """Verify upload-time code owns Enhanced Citations container readiness."""
    print("Testing upload-time Enhanced Citations container readiness...")

    helper_source = get_function_source(FUNCTIONS_DOCUMENTS_PATH, "_ensure_blob_container_ready")
    upload_source = get_function_source(FUNCTIONS_DOCUMENTS_PATH, "upload_to_blob")

    if "container_client.create_container()" not in helper_source:
        raise AssertionError("Upload-time helper should create missing containers on demand.")
    if "ResourceExistsError" not in helper_source:
        raise AssertionError("Upload-time helper should tolerate containers that already exist.")
    if "_ensure_blob_container_ready(blob_service_client, storage_account_container_name)" not in upload_source:
        raise AssertionError("upload_to_blob must ensure the target container is ready before uploading.")
    if "raise RuntimeError" not in upload_source:
        raise AssertionError("upload_to_blob should propagate a stable feature-scoped failure.")

    print("Upload path owns Enhanced Citations container readiness.")


def test_admin_storage_status_and_connection_test_are_exposed():
    """Verify admins can see startup status and explicitly test storage reachability."""
    print("Testing admin Enhanced Citations storage diagnostics...")

    frontend_route = read_text(ROUTE_FRONTEND_ADMIN_SETTINGS_PATH)
    backend_route = read_text(ROUTE_BACKEND_SETTINGS_PATH)
    template = read_text(ADMIN_SETTINGS_TEMPLATE_PATH)
    admin_js = read_text(ADMIN_SETTINGS_JS_PATH)

    required_snippets = [
        (frontend_route, "get_enhanced_citations_storage_status()"),
        (frontend_route, "enhanced_citations_storage_status"),
        (backend_route, "test_type == 'enhanced_citations_storage'"),
        (backend_route, "def _test_enhanced_citations_storage_connection(data):"),
        (template, "enhanced-citations-storage-startup-status"),
        (template, "Test Enhanced Citations Storage"),
        (template, "Startup skips live storage container checks"),
        (admin_js, "test_type: 'enhanced_citations_storage'"),
        (admin_js, "test_enhanced_citations_storage_button"),
        (admin_js, "renderEnhancedCitationsStorageTestData"),
    ]

    for source, snippet in required_snippets:
        if snippet not in source:
            raise AssertionError(f"Missing admin diagnostics snippet: {snippet}")

    print("Admin diagnostics expose startup status and explicit storage testing.")


if __name__ == "__main__":
    tests = [
        test_startup_storage_initialization_is_non_blocking,
        test_upload_path_owns_container_readiness,
        test_admin_storage_status_and_connection_test_are_exposed,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    passed = sum(results)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
