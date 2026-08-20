# test_cosmos_wave4a1_admin_document_access_ui.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 4A1 document access admin UI.
Version: 0.250.047
Implemented in: 0.250.011
Default read enablement updated in: 0.250.027
Redis DAI cache dashboard updated in: 0.250.029
Maintenance status gates updated in: 0.250.030
DAI debug UI cleanup updated in: 0.250.031
Conversation cache controls updated in: 0.250.033
Conversation cache metrics updated in: 0.250.034
Conversation mark-read cache invalidation tuned in: 0.250.035

This test ensures Admin Settings exposes safe document_access_index
operational controls, status polling hooks, manual batch execution,
reset confirmation, and the Wave 5B default read path.
"""

import os
import sys
from test_support.versioning import assert_app_version_at_least
from test_support.templates import compose_if_admin_settings


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")


def _read(relative_path):
    _path = os.path.join(ROOT_DIR, relative_path)
    with open(_path, "r", encoding="utf-8") as file:
        return compose_if_admin_settings(_path, file.read())


def test_admin_template_exposes_safe_document_access_controls():
    """The Scale tab should render document access index status and safe controls."""
    template = _read(os.path.join("application", "single_app", "templates", "admin_settings.html"))
    required_ids = [
        "document-access-index-section",
        "enable_document_access_index_write_through",
        "enable_startup_document_access_index_backfill",
        "document_access_index_backfill_batch_size",
        "document_access_index_repair_batch_size",
        "enable_document_access_index_shadow_validation",
        "document-access-index-refresh-btn",
        "document-access-index-run-batch-btn",
        "document-access-index-reset-btn",
        "documentAccessIndexResetModal",
        "document-access-index-reset-confirm-btn",
        "document-access-index-backfill-status",
        "document-access-index-repair-count",
        "document-access-index-maintenance-mode",
        "document-access-index-maintenance-next-action",
        "document-access-index-maintenance-more-work",
        "document-access-index-maintenance-active-interval",
        "document-access-index-read-15m-attempts",
        "document-access-index-read-15m-served",
        "document-access-index-read-15m-fallbacks",
        "document-access-index-read-15m-fallback-rate",
        "document-access-index-read-15m-ru",
        "document-access-index-read-15m-latency",
        "document-access-index-read-last-fallback",
        "document-access-index-read-last-sample",
        "document-access-index-shadow-last-status",
        "document-access-index-shadow-mismatches",
        "document-access-index-shadow-ru-comparison",
        "document-access-index-shadow-validation-ru",
        "document-access-index-shadow-candidate-ru",
        "document-access-index-shadow-wave5-ru-savings",
        "document-access-index-shadow-ms-comparison",
        "document-access-index-shadow-ms-savings",
        "document-access-index-rolling-5m-ru-comparison",
        "document-access-index-rolling-5m-wave5-ru-savings",
        "document-access-index-rolling-15m-ru-comparison",
        "document-access-index-rolling-15m-wave5-ru-savings",
        "document-access-index-rolling-15m-validation-overhead",
        "document-access-index-rolling-15m-samples",
        "conversation-cache-section",
        "conversation-cache-refresh-btn",
        "enable_conversation_cache",
        "conversation_cache_ttl_seconds",
        "conversation-cache-runtime-status",
        "conversation-cache-15m-hit-rate",
        "conversation-cache-15m-hits-misses",
        "conversation-cache-15m-bypasses-errors",
        "conversation-cache-15m-writes-invalidations",
        "conversation-cache-15m-operation-counts",
        "conversation-cache-last-event",
        "conversation-cache-last-invalidation",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert "Cosmos Document Access Index" in template
    assert "Document access projection maintenance is automatic." in template
    assert "Production read metrics below show DAI-served reads, Redis cache hits, source fallbacks, RU, and latency without requiring shadow validation." in template
    assert "Rolling decision metrics aggregate shadow-validation samples over recent windows." in template
    assert "Document access index reads" in template
    assert "Enable shadow validation" in template
    assert 'name="enable_document_access_index_reads"' in template
    assert "Wave 5B default" in template
    assert "Wave 6" in template
    assert "Redis document list cache" in template
    assert "Conversation Cache" in template
    assert "Enable conversation cache" in template
    assert 'name="enable_conversation_cache"' in template
    assert 'name="conversation_cache_ttl_seconds"' in template
    assert "Redis is optional; cache misses and disabled cache paths continue using source Cosmos queries." in template
    assert "15m Cache Hit Rate" in template
    assert "15m Writes / Invalidations" in template
    assert "Phase 4" not in template[template.index('id="conversation-cache-section"'):template.index('id="document-access-index-section"')]
    assert 'name="enable_document_access_index_shadow_validation"' in template
    assert "{% if enable_dai_debug %}" in template
    assert "data-testid=\"document-access-index-debug-controls\"" in template
    assert "data-testid=\"document-access-index-debug-read-controls\"" in template
    assert 'name="enable_dai_debug"' not in template


def test_admin_save_persists_document_access_settings():
    """Admin settings POST should preserve hidden DAI debug controls safely."""
    route_source = _read(os.path.join("application", "single_app", "route_frontend_admin_settings.py"))
    backend_route_source = _read(os.path.join("application", "single_app", "route_backend_settings.py"))

    assert "'enable_document_access_index_write_through': True" in route_source
    assert "'enable_startup_document_access_index_backfill': True" in route_source
    assert "'document_access_index_active_maintenance_interval_seconds': settings.get(" in route_source
    assert "'document_access_index_backfill_batch_size': document_access_index_backfill_batch_size" in route_source
    assert "'document_access_index_repair_batch_size': document_access_index_repair_batch_size" in route_source
    assert "'enable_document_access_index_reads': True" in route_source
    assert "'enable_dai_debug': dai_debug_enabled" in route_source
    assert "dai_debug_enabled = bool(settings.get('enable_dai_debug', False))" in route_source
    assert "'enable_document_access_index_cache': document_access_index_cache_enabled" in route_source
    assert "'document_access_index_cache_ttl_seconds': document_access_index_cache_ttl_seconds" in route_source
    assert "'enable_conversation_cache': form_data.get('enable_conversation_cache') == 'on'" in route_source
    assert "'conversation_cache_ttl_seconds': conversation_cache_ttl_seconds" in route_source
    assert "settings.get('conversation_cache_ttl_seconds', 120)" in route_source
    assert "'enable_document_access_index_shadow_validation': document_access_index_shadow_validation_enabled" in route_source
    assert "settings.get('document_access_index_cache_ttl_seconds', 900)" in route_source
    assert "if 'apply_cosmos_indexing_policies' in payload:" in backend_route_source
    assert "apply_indexing_policies=apply_indexing_policies" in backend_route_source


def test_document_access_status_contract_includes_dashboard_settings():
    """Status payload should include the flags needed by the admin dashboard."""
    index_source = _read(os.path.join("application", "single_app", "functions_document_access_index.py"))
    maintenance_source = _read(os.path.join("application", "single_app", "functions_app_maintenance.py"))
    conversation_cache_source = _read(os.path.join("application", "single_app", "functions_conversation_cache.py"))

    assert "'write_through_enabled': True" in index_source
    assert "'startup_backfill_enabled': True" in index_source
    assert "'container_enabled': normalized_settings.get('container_enabled')" in index_source
    assert "'write_through_enabled': normalized_settings.get('write_through_enabled')" in index_source
    assert "'reads_enabled': normalized_settings.get('reads_enabled')" in index_source
    assert "'shadow_validation_enabled': normalized_settings.get('shadow_validation_enabled')" in index_source
    assert "'startup_backfill_enabled': normalized_settings.get('startup_backfill_enabled')" in index_source
    assert "'read_metrics': get_document_access_index_read_metrics()" in index_source
    assert "'cache_metrics': get_document_access_index_cache_metrics()" in index_source
    assert "'cache_enabled': normalized_settings.get('cache_enabled')" in index_source
    assert "'cache_ttl_seconds': normalized_settings.get('cache_ttl_seconds')" in index_source
    assert "'maintenance': _build_document_access_index_maintenance_summary(" in index_source
    assert "'shadow_validation': shadow_validation" in index_source
    assert "'source_query_ru': None" in index_source
    assert "'projection_query_ru': None" in index_source
    assert "'validation_index_ru': None" in index_source
    assert "'candidate_read_ru': None" in index_source
    assert "'estimated_ru_savings': None" in index_source
    assert "'estimated_wave5_ru_savings': None" in index_source
    assert "'source_query_ms': None" in index_source
    assert "'projection_query_ms': None" in index_source
    assert "'validation_index_ms': None" in index_source
    assert "'candidate_read_ms': None" in index_source
    assert "'estimated_ms_savings': None" in index_source
    assert "'estimated_wave5_ms_savings': None" in index_source
    assert "shadow_validation['rolling_metrics'] = _empty_shadow_rolling_metrics()" in index_source
    assert "get_conversation_cache_metrics" in maintenance_source
    assert "get_conversation_cache_settings" in maintenance_source
    assert "'conversation_cache': {" in maintenance_source
    assert "'metrics': get_conversation_cache_metrics()" in maintenance_source
    assert "def get_conversation_cache_metrics()" in conversation_cache_source
    assert "CONVERSATION_CACHE_METRIC_WINDOWS_MINUTES = (5, 15, 60)" in conversation_cache_source


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
    assert "function getDocumentAccessIndexRollingWindow" in admin_js
    assert "function getDocumentAccessIndexReadWindow" in admin_js
    assert "document-access-index-read-15m-fallback-rate" in admin_js
    assert "function renderConversationCacheStatus" in admin_js
    assert "function formatConversationCacheOperationCounts" in admin_js
    assert "conversation-cache-refresh-btn" in admin_js
    assert "conversation-cache-15m-hit-rate" in admin_js
    assert "conversation-cache-15m-writes-invalidations" in admin_js
    assert "document-access-index-maintenance-next-action" in admin_js
    assert "formatDocumentAccessIndexSampleSummary" in admin_js
    assert "function isDocumentAccessIndexBackfillActive" not in admin_js
    assert "documentAccessIndexResetModal" in admin_js
    assert "bootstrap.Modal.getInstance(modalElement)?.hide();" in admin_js
    assert "return ['running', 'in_progress'].includes" not in document_access_js
    assert "confirm(" not in document_access_js
    assert "alert(" not in document_access_js


def test_wave4a1_version_is_current():
    """Config version should reflect the current cache admin UI change."""
    config_source = _read(os.path.join("application", "single_app", "config.py"))

    assert_app_version_at_least("0.250.047")


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
