# test_admin_enhanced_citations_storage_status.py
"""
UI test for Admin Settings Enhanced Citations storage status.
Version: 0.250.126
Implemented in: 0.250.126

This test ensures the Admin Settings Enhanced Citations section exposes a
non-blocking startup storage status and a safe explicit storage test action.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
ADMIN_SETTINGS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"
ROUTE_FRONTEND_ADMIN_SETTINGS = REPO_ROOT / "application" / "single_app" / "route_frontend_admin_settings.py"
ROUTE_BACKEND_SETTINGS = REPO_ROOT / "application" / "single_app" / "route_backend_settings.py"


def _read_text(path):
    return path.read_text(encoding="utf-8")


def _extract_function(source, function_name):
    marker = f"const {function_name} = "
    start = source.index(marker)
    end = source.index("\n    const ", start + len(marker))
    return source[start:end]


def test_admin_enhanced_citations_storage_status_contract():
    """Validate static Admin Settings storage status and test-button wiring."""
    template = _read_text(ADMIN_TEMPLATE)
    admin_js = _read_text(ADMIN_SETTINGS_JS)
    frontend_route = _read_text(ROUTE_FRONTEND_ADMIN_SETTINGS)
    backend_route = _read_text(ROUTE_BACKEND_SETTINGS)

    required_template_snippets = [
        'id="enhanced-citations-storage-startup-status"',
        'id="test_enhanced_citations_storage_button"',
        'id="test_enhanced_citations_storage_result"',
        "Enhanced Citations storage startup status",
        "Startup skips live storage container checks",
        "Test Enhanced Citations Storage",
    ]
    for snippet in required_template_snippets:
        assert snippet in template

    assert "get_enhanced_citations_storage_status()" in frontend_route
    assert "enhanced_citations_storage_status" in frontend_route
    assert "test_type == 'enhanced_citations_storage'" in backend_route
    assert "def _test_enhanced_citations_storage_connection(data):" in backend_route

    required_js_snippets = [
        "buildEnhancedCitationsStoragePayload",
        "renderEnhancedCitationsStorageTestData",
        "runEnhancedCitationsStorageTest",
        "test_enhanced_citations_storage_button",
        "test_enhanced_citations_storage_result",
        "test_type: 'enhanced_citations_storage'",
    ]
    for snippet in required_js_snippets:
        assert snippet in admin_js

    render_function = _extract_function(admin_js, "renderEnhancedCitationsStorageTestData")
    run_function = _extract_function(admin_js, "runEnhancedCitationsStorageTest")
    assert "renderAdminTestResult" in render_function
    assert "renderAdminTestLoading" in run_function
    assert "innerHTML" not in render_function
    assert "innerHTML" not in run_function
