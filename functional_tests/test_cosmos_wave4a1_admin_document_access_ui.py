# test_cosmos_wave4a1_admin_document_access_ui.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 4A1 document access admin UI.
Version: 0.250.011
Implemented in: 0.250.011

This test ensures Admin Settings exposes safe document_access_index
operational controls, status polling hooks, manual batch execution,
and reset confirmation without enabling read-path switchover.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")


def _read(relative_path):
    with open(os.path.join(ROOT_DIR, relative_path), "r", encoding="utf-8") as file:
        return file.read()


def test_admin_template_exposes_safe_document_access_controls():
    """The Scale tab should render document access index status and safe controls."""
    template = _read(os.path.join("application", "single_app", "templates", "admin_settings.html"))
    required_ids = [
        "document-access-index-section",
        "enable_document_access_index_write_through",
        "enable_startup_document_access_index_backfill",
        "document_access_index_backfill_batch_size",
        "document_access_index_repair_batch_size",
        "document-access-index-refresh-btn",
        "document-access-index-run-batch-btn",
        "document-access-index-reset-btn",
        "documentAccessIndexResetModal",
        "document-access-index-reset-confirm-btn",
        "document-access-index-backfill-status",
        "document-access-index-repair-count",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert "Cosmos Document Access Index" in template
    assert "Read switchover and shadow validation remain future-wave controls." in template
    assert "Enable document access index reads" in template
    assert "Enable shadow validation" in template
    assert 'name="enable_document_access_index_reads"' not in template
    assert 'name="enable_document_access_index_shadow_validation"' not in template


def test_admin_save_persists_document_access_settings():
    """Admin settings POST should save only the current safe 4A1 controls."""
    route_source = _read(os.path.join("application", "single_app", "route_frontend_admin_settings.py"))
    backend_route_source = _read(os.path.join("application", "single_app", "route_backend_settings.py"))

    assert "'enable_document_access_index_write_through': form_data.get('enable_document_access_index_write_through') == 'on'" in route_source
    assert "'enable_startup_document_access_index_backfill': form_data.get('enable_startup_document_access_index_backfill') == 'on'" in route_source
    assert "'document_access_index_backfill_batch_size': document_access_index_backfill_batch_size" in route_source
    assert "'document_access_index_repair_batch_size': document_access_index_repair_batch_size" in route_source
    assert "'enable_document_access_index_reads': bool(settings.get('enable_document_access_index_reads', False))" in route_source
    assert "'enable_document_access_index_shadow_validation': bool(settings.get('enable_document_access_index_shadow_validation', False))" in route_source
    assert "if 'apply_cosmos_indexing_policies' in payload:" in backend_route_source
    assert "apply_indexing_policies=apply_indexing_policies" in backend_route_source


def test_document_access_status_contract_includes_dashboard_settings():
    """Status payload should include the flags needed by the admin dashboard."""
    index_source = _read(os.path.join("application", "single_app", "functions_document_access_index.py"))

    assert "'container_enabled': normalized_settings.get('container_enabled')" in index_source
    assert "'write_through_enabled': normalized_settings.get('write_through_enabled')" in index_source
    assert "'reads_enabled': normalized_settings.get('reads_enabled')" in index_source
    assert "'shadow_validation_enabled': normalized_settings.get('shadow_validation_enabled')" in index_source
    assert "'startup_backfill_enabled': normalized_settings.get('startup_backfill_enabled')" in index_source


def test_admin_javascript_uses_existing_maintenance_api_safely():
    """Client-side controls should use Bootstrap/DOM APIs and the maintenance endpoints."""
    admin_js = _read(os.path.join("application", "single_app", "static", "js", "admin", "admin_settings.js"))
    document_access_js = admin_js[
        admin_js.index("function setDocumentAccessIndexMessage"):
        admin_js.index("function setupCosmosThroughputControls")
    ]

    assert "function setupDocumentAccessIndexControls()" in admin_js
    assert "function loadDocumentAccessIndexStatus" in admin_js
    assert "function runDocumentAccessIndexBackfillBatch" in admin_js
    assert "'/api/admin/settings/app-maintenance/status'" in admin_js
    assert "'/api/admin/settings/app-maintenance/run'" in admin_js
    assert "apply_cosmos_indexing_policies: false" in admin_js
    assert "run_document_access_index_backfill: true" in admin_js
    assert "reset_document_access_index_backfill: reset" in admin_js
    assert "function isDocumentAccessIndexBackfillRunning" in admin_js
    assert "getNormalizedDocumentAccessIndexStatus(status) === 'running'" in admin_js
    assert "function isDocumentAccessIndexBackfillInProgress" in admin_js
    assert "function isDocumentAccessIndexBackfillActive" not in admin_js
    assert "documentAccessIndexResetModal" in admin_js
    assert "bootstrap.Modal.getInstance(modalElement)?.hide();" in admin_js
    assert "return ['running', 'in_progress'].includes" not in document_access_js
    assert "confirm(" not in document_access_js
    assert "alert(" not in document_access_js


def test_wave4a1_version_is_current():
    """Config version should reflect the Wave 4A1 code change."""
    config_source = _read(os.path.join("application", "single_app", "config.py"))

    assert 'VERSION = "0.250.011"' in config_source


if __name__ == "__main__":
    tests = [
        test_admin_template_exposes_safe_document_access_controls,
        test_admin_save_persists_document_access_settings,
        test_document_access_status_contract_includes_dashboard_settings,
        test_admin_javascript_uses_existing_maintenance_api_safely,
        test_wave4a1_version_is_current,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("Test passed.")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    sys.exit(0 if all(results) else 1)
