#!/usr/bin/env python3
# test_document_search_action_scope_enforcement.py
"""
Functional test for document search action scope enforcement.
Version: 0.261.310
Implemented in: 0.261.276

This test ensures that document-search action settings narrow runtime scopes
without broadening user access, and that page-based summary target lengths are
normalized while legacy custom values remain compatible.
"""

import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = REPO_ROOT / "application" / "single_app" / "semantic_kernel_plugins" / "document_search_plugin.py"
sys.path.insert(0, str(PLUGIN_PATH.parents[1]))

from public_chat_scope import public_chat_scope_context  # noqa: E402


def normalize_search_scope(doc_scope, default_scope="all"):
    normalized_scope = str(doc_scope or default_scope).strip().lower()
    return normalized_scope if normalized_scope in {"all", "personal", "group", "public"} else default_scope


def normalize_search_id_list(raw_ids):
    if raw_ids is None:
        return []
    if isinstance(raw_ids, str):
        values = [value.strip() for value in raw_ids.split(",") if value.strip()]
    elif isinstance(raw_ids, list):
        values = [str(value).strip() for value in raw_ids if str(value).strip()]
    else:
        values = [str(raw_ids).strip()] if str(raw_ids).strip() else []
    normalized = []
    for value in values:
        if value not in normalized:
            normalized.append(value)
    return normalized


def install_module_stubs():
    semantic_kernel = types.ModuleType("semantic_kernel")
    semantic_kernel_functions = types.ModuleType("semantic_kernel.functions")
    semantic_kernel_functions.kernel_function = lambda *args, **kwargs: (lambda func: func)
    sys.modules["semantic_kernel"] = semantic_kernel
    sys.modules["semantic_kernel.functions"] = semantic_kernel_functions

    contracts = types.ModuleType("content_screening.contracts")

    class ScreeningError(Exception):
        public_message = "Screened"
        code = "screened"
        status_code = 400

    contracts.ScreeningError = ScreeningError
    sys.modules["content_screening.contracts"] = contracts

    auth = types.ModuleType("functions_authentication")
    auth.get_current_user_id = lambda: "test-user"
    sys.modules["functions_authentication"] = auth

    citations = types.ModuleType("functions_agent_document_citations")
    citations.annotate_document_search_payload = lambda payload, _name: payload
    sys.modules["functions_agent_document_citations"] = citations

    search = types.ModuleType("functions_search")
    search.SEARCH_DEFAULT_TOP_N = 12
    search.SEARCH_MAX_TOP_N = 500
    search.normalize_search_id_list = normalize_search_id_list
    search.normalize_search_scope = normalize_search_scope
    search.normalize_search_top_n = lambda value, default, maximum: min(maximum, int(value)) if int(value) > 0 else default
    sys.modules["functions_search"] = search

    search_service = types.ModuleType("functions_search_service")
    search_service.SUMMARY_DEFAULT_FINAL_TARGET = "2 pages"
    search_service.SUMMARY_DEFAULT_WINDOW_SUMMARY_TARGET = "2 pages"
    search_service.SUMMARY_DEFAULT_WINDOW_UNIT = "pages"
    search_service.get_document_chunks_payload = lambda **kwargs: {"operation": "chunks", **kwargs}
    search_service.search_documents = lambda **kwargs: {"operation": "search", "results": [], **kwargs}
    search_service.summarize_document_content = lambda **kwargs: {"operation": "summary", **kwargs}
    sys.modules["functions_search_service"] = search_service

    base_module = types.ModuleType("semantic_kernel_plugins.base_plugin")

    class BasePlugin:
        def __init__(self, manifest=None):
            self.manifest = manifest or {}

    base_module.BasePlugin = BasePlugin
    sys.modules["semantic_kernel_plugins.base_plugin"] = base_module

    logger_module = types.ModuleType("semantic_kernel_plugins.plugin_invocation_logger")
    logger_module.plugin_function_logger = lambda _name: (lambda func: func)
    sys.modules["semantic_kernel_plugins.plugin_invocation_logger"] = logger_module


def load_plugin_module():
    install_module_stubs()
    spec = importlib.util.spec_from_file_location("document_search_plugin_under_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_scope_helper_defaults_and_restrictions():
    plugin_module = load_plugin_module()

    assert plugin_module.normalize_allowed_search_scopes({}) == ["personal", "group", "public"]
    assert plugin_module.normalize_allowed_search_scopes({"allowed_scopes": ["group", "bogus", "public", "group"]}) == ["group", "public"]
    assert plugin_module.normalize_allowed_search_scopes({"allowed_scopes": []}) == []
    assert plugin_module.resolve_allowed_scope_requests("all", ["group", "public"]) == ["group", "public"]
    assert plugin_module.resolve_allowed_scope_requests("personal", ["group", "public"]) == []
    assert plugin_module.intersect_allowed_search_ids("g1,g2", ["g2", "g3"]) == ["g2"]
    assert plugin_module.intersect_allowed_search_ids("", ["g2", "g3"]) == ["g2", "g3"]
    assert plugin_module.intersect_allowed_search_ids("g1,g2", []) == "g1,g2"


def test_aggregate_public_scope_cannot_bypass_action_scope_or_workspace_restrictions():
    plugin_module = load_plugin_module()
    calls = []
    plugin_module.run_document_search = lambda **kwargs: calls.append(kwargs) or {"results": []}
    private = plugin_module.DocumentSearchPlugin({"additionalFields": {"allowed_scopes": ["personal"]}})
    public = plugin_module.DocumentSearchPlugin({"additionalFields": {
        "allowed_scopes": ["public"], "allowed_public_workspace_ids": ["p2"],
    }})
    with public_chat_scope_context("test-user", "all", ["p1", "p2"]):
        denied = private.search_documents(query="policy", doc_scope="personal")
        allowed = public.search_documents(query="policy", doc_scope="all")
        other = public.search_documents(query="policy", active_public_workspace_id="outside")
    assert denied == {"error": "Document search scope is not allowed for this action."}
    assert "error" not in allowed and len(calls) == 1
    assert calls[0]["doc_scope"] == "public" and calls[0]["active_public_workspace_id"] == ["p2"]
    assert "error" in other


def test_search_documents_skips_disabled_scopes_and_intersects_ids():
    plugin_module = load_plugin_module()
    calls = []

    def fake_search_documents(**kwargs):
        calls.append(kwargs)
        return {
            "results": [{"document_id": f"doc-{kwargs['doc_scope']}", "scope": kwargs["doc_scope"]}],
            "result_count": 1,
            "document_count": 1,
            "query": kwargs["query"],
            "scope": kwargs["doc_scope"],
            "top_n": kwargs["top_n"],
        }

    plugin_module.run_document_search = fake_search_documents
    plugin = plugin_module.DocumentSearchPlugin({
        "additionalFields": {
            "allowed_scopes": ["group", "public"],
            "allowed_group_ids": ["g2", "g3"],
            "allowed_public_workspace_ids": ["p2"],
            "default_top_n": 3,
        },
    })

    payload = plugin.search_documents(
        query="policy",
        doc_scope="all",
        active_group_ids="g1,g2",
        active_public_workspace_id="p1,p2",
    )

    assert [call["doc_scope"] for call in calls] == ["group", "public"]
    assert calls[0]["active_group_ids"] == ["g2"]
    assert calls[0]["active_public_workspace_id"] == ["p2"]
    assert calls[1]["active_group_ids"] == ["g2"]
    assert calls[1]["active_public_workspace_id"] == ["p2"]
    assert payload["allowed_scopes"] == ["group", "public"]
    assert payload["result_count"] == 2
    assert [result["scope"] for result in payload["results"]] == ["group", "public"]


def test_search_documents_rejects_disabled_specific_scope():
    plugin_module = load_plugin_module()
    calls = []
    plugin_module.run_document_search = lambda **kwargs: calls.append(kwargs) or {"results": []}
    plugin = plugin_module.DocumentSearchPlugin({"additionalFields": {"allowed_scopes": ["group"]}})

    payload = plugin.search_documents(query="policy", doc_scope="personal")

    assert calls == []
    assert payload == {"error": "Document search scope is not allowed for this action."}


def test_target_length_parsing_and_normalization():
    plugin_module = load_plugin_module()

    assert plugin_module.parse_page_target_length("2 pages", 1, 10) == 2
    assert plugin_module.parse_page_target_length("1 page", 1, 10) == 1
    assert plugin_module.parse_page_target_length("15 pages", 1, 10) == 10
    assert plugin_module.parse_page_target_length("500 words", 1, 10) is None
    assert plugin_module.normalize_summary_target_length("", "2 pages", 1, 10) == "2 pages"
    assert plugin_module.normalize_summary_target_length("15 pages", "2 pages", 1, 10) == "10 pages"
    assert plugin_module.normalize_summary_target_length("500 words", "2 pages", 1, 10) == "500 words"

    plugin = plugin_module.DocumentSearchPlugin({
        "additionalFields": {
            "default_window_target_length": "99 pages",
            "default_final_target_length": "500 words",
        },
    })
    assert plugin._resolve_target_length("", "default_window_target_length", "2 pages") == "10 pages"
    assert plugin._resolve_target_length("", "default_final_target_length", "2 pages") == "500 words"


if __name__ == "__main__":
    tests = [
        test_scope_helper_defaults_and_restrictions,
        test_aggregate_public_scope_cannot_bypass_action_scope_or_workspace_restrictions,
        test_search_documents_skips_disabled_scopes_and_intersects_ids,
        test_search_documents_rejects_disabled_specific_scope,
        test_target_length_parsing_and_normalization,
    ]
    for test in tests:
        print(f"Running {test.__name__}...")
        test()
    print("All document search action scope enforcement tests passed.")
