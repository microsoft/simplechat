#!/usr/bin/env python3
"""
Functional test for document-search action save validation fallback.
Version: 0.241.024
Implemented in: 0.241.024

This test ensures the action modal no longer surfaces raw HTML 404 pages when
the pre-save validation endpoint is unavailable and that document_search schema
aliases exist for save-time compatibility.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_COMMON_PATH = REPO_ROOT / "application" / "single_app" / "static" / "js" / "plugin_common.js"
DOCUMENT_SEARCH_DEFINITION_PATH = REPO_ROOT / "application" / "single_app" / "static" / "json" / "schemas" / "document_search.definition.json"
DOCUMENT_SEARCH_SCHEMA_PATH = REPO_ROOT / "application" / "single_app" / "static" / "json" / "schemas" / "document_search_plugin.additional_settings.schema.json"


def test_document_search_action_save_validation_fallback():
    """Ensure validation 404s no longer block document-search action saves."""
    plugin_common_source = PLUGIN_COMMON_PATH.read_text(encoding="utf-8")
    definition_source = DOCUMENT_SEARCH_DEFINITION_PATH.read_text(encoding="utf-8")
    schema_source = DOCUMENT_SEARCH_SCHEMA_PATH.read_text(encoding="utf-8")

    assert "if (response.status === 404)" in plugin_common_source
    assert "Validation endpoint unavailable; using save-time validation only." in plugin_common_source
    assert "Requested API endpoint was not found." in plugin_common_source
    assert '"NoAuth"' in definition_source
    assert '"default_doc_scope"' in schema_source
    assert '"default_final_target_length"' in schema_source