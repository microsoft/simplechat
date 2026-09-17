# test_content_screening_read_boundaries.py
"""
Behavioral tests for search, native caches, and resumed source consumption.
Version: 0.261.113
Implemented in: 0.261.106

Executes the actual boundary function bodies with isolated fake dependencies.
Azure Search, Cosmos, Blob Storage, and model providers are never contacted.
"""

import ast
import asyncio
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
import unittest

from flask import jsonify, request
from test_content_screening_access import APP_ROOT, FakeContainer, ScreeningAccessFixture
from content_screening import access
from content_screening.contracts import DocumentHeldError, ScreeningConflictError, ScreeningError, document_is_available, hash_payload


def load_functions(file_name, names, namespace, *, constants=False):
    path = APP_ROOT / file_name
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
        or constants and isinstance(node, ast.Assign) and all(
            isinstance(target, ast.Name) and target.id.isupper() for target in node.targets
        )
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class SearchBoundaryTests(ScreeningAccessFixture):
    def search_namespace(self):
        path = APP_ROOT / "functions_search.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.cached_results = None
        self.search_calls = []
        self.index_results = []
        self.on_cache_write = None

        def search(**kwargs):
            self.search_calls.append(kwargs)
            return self.index_results

        def cache(*_args, **_kwargs):
            if self.on_cache_write:
                self.on_cache_write()

        namespace = {
            "hashlib": hashlib, "List": List, "Dict": Dict, "Any": Any,
            "assert_document_available": access.assert_document_available,
            "assert_evidence_available": access.assert_evidence_available,
            "document_provenance": access.document_provenance,
            "PROVENANCE_FIELD": access.PROVENANCE_FIELD,
            "filter_available_results": access.filter_available_results,
            "get_user_visible_public_workspace_ids_from_settings": lambda _user: [],
            "debug_print": lambda *_args, **_kwargs: None,
            "logger": SimpleNamespace(info=lambda *_args, **_kwargs: None),
            "generate_search_cache_key": lambda **_kwargs: "test-key",
            "get_cached_search_results": lambda *_args, **_kwargs: self.cached_results,
            "cache_search_results": cache,
            "generate_embedding": lambda _query, **_kwargs: [0.1],
            "read_embedding_settings": lambda: {},
            "active_embedding_profile": lambda _settings: SimpleNamespace(profile_id="fixture-profile"),
            "embedding_query_slot": lambda _profile_id: nullcontext(),
            "embedding_search_filter": lambda *_args: None,
            "search_with_embedding_profile": lambda client, _profile, **kwargs: client.search(**kwargs),
            "VectorizedQuery": lambda **kwargs: kwargs,
            "CLIENTS": {f"search_client_{scope}": SimpleNamespace(search=search) for scope in ("user", "group", "public")},
            "DEBUG_ENABLED": False,
            "is_semantic_search_quota_error": lambda _error: False,
            "clear_semantic_search_quota_warning": lambda **_kwargs: None,
        }
        return load_functions("functions_search.py", names, namespace, constants=True)

    def azure_result(self):
        return {
            **self.search_result(), "chunk_id": "1", "page_number": 1,
            "upload_date": "2026-09-08", "document_classification": "None",
            "author": ["old"], "@search.score": 1.0,
        }

    def test_hybrid_cache_hit_is_not_a_positive_authorization(self):
        namespace = self.search_namespace()
        self.cached_results = access.filter_available_results([self.search_result()], "user-1")
        self.hold()
        result = namespace["hybrid_search"]("question", "user-1", doc_scope="personal")
        self.assertEqual(result, [])
        self.assertEqual(len(self.search_calls), 1)

    def test_hybrid_fresh_results_are_checked_again_before_return(self):
        namespace = self.search_namespace()
        self.index_results = [self.azure_result()]
        self.on_cache_write = self.hold
        result = namespace["hybrid_search"]("question", "user-1", doc_scope="personal")
        self.assertEqual(result, [])
        self.assertEqual(len(self.search_calls), 1)

    def test_explicit_held_search_selection_errors_without_embedding_or_search(self):
        namespace = self.search_namespace()
        self.hold()
        with self.assertRaises(DocumentHeldError):
            namespace["hybrid_search"]("question", "user-1", doc_scope="personal", document_ids=["document-1"])
        self.assertEqual(self.search_calls, [])

    def test_explicit_selection_held_during_search_never_becomes_empty_context(self):
        namespace = self.search_namespace()
        self.index_results = [self.azure_result()]
        self.on_cache_write = self.hold
        with self.assertRaises(DocumentHeldError):
            namespace["hybrid_search"]("question", "user-1", doc_scope="personal", document_ids=["document-1"])

    def test_workspace_cache_keys_change_on_holds_and_clean_replacements(self):
        for function_name, container_name, scope_id in (
            ("get_personal_document_fingerprint", "cosmos_user_documents_container", "user-1"),
            ("get_group_document_fingerprint", "cosmos_group_documents_container", "group-1"),
            ("get_public_workspace_document_fingerprint", "cosmos_public_documents_container", "workspace-1"),
        ):
            with self.subTest(scope=scope_id):
                document = deepcopy(self.document)
                queries = []

                def query_items(query, parameters, **_kwargs):
                    queries.append((query, parameters))
                    return [deepcopy(document)]

                namespace = {
                    "hashlib": hashlib, "SCREENING_FIELD": "content_screening", "hash_payload": hash_payload,
                    "_debug_print": lambda *_args, **_kwargs: None,
                    container_name: SimpleNamespace(query_items=query_items),
                }
                load_functions(
                    "utils_cache.py", {"_document_cache_identity", function_name}, namespace,
                )
                first = namespace[function_name](scope_id)
                document["content_screening"]["state"] = "pending_review"
                held = namespace[function_name](scope_id)
                document["content_screening"]["state"] = "cleared"
                document["content_screening"]["availability_generation"] += 1
                replacement = namespace[function_name](scope_id)
                self.assertEqual(len({first, held, replacement}), 3)
                self.assertTrue(all("c.content_screening" in query for query, _params in queries))
                if scope_id != "workspace-1":
                    self.assertIn(f"{scope_id},approved", [value["value"] for value in queries[0][1]])

    def test_explicit_full_document_fetch_checks_before_loading_any_chunks(self):
        reads = []
        context = {"scope": "personal", "document": deepcopy(self.document)}
        namespace = {
            "PROVENANCE_FIELD": access.PROVENANCE_FIELD,
            "assert_document_available": access.assert_document_available,
            "assert_document_chunks_available": access.assert_document_chunks_available,
            "assert_evidence_available": access.assert_evidence_available,
            "document_provenance": access.document_provenance,
            "resolve_document_context": lambda **_kwargs: context,
            "get_ordered_document_chunks": lambda **_kwargs: reads.append(True),
        }
        load_functions("functions_search_service.py", {"get_document_chunks_payload"}, namespace)
        self.hold()
        with self.assertRaises(DocumentHeldError):
            namespace["get_document_chunks_payload"]("document-1", "user-1")
        self.assertEqual(reads, [])

    def test_chat_readiness_cannot_infer_clearance_from_progress(self):
        namespace = load_functions(
            "route_backend_chats.py", {"_is_search_ready_chat_upload_workspace_document"},
            {"document_is_available": document_is_available},
        )
        self.document.update({"percentage_complete": 100, "status": "Processing complete", "num_chunks": 5})
        self.hold()
        self.assertFalse(namespace["_is_search_ready_chat_upload_workspace_document"](self.document))
        del self.document["content_screening"]
        self.assertTrue(namespace["_is_search_ready_chat_upload_workspace_document"](self.document))

    def test_chat_selected_document_projection_does_not_hide_new_hold(self):
        stale = deepcopy(self.document)
        del stale["content_screening"]
        self.personal.query_items = lambda **_kwargs: [stale]
        namespace = load_functions(
            "route_backend_chats.py",
            {"_normalize_requested_scope_ids", "_resolve_chat_selected_document_metadata"},
            {
                "cosmos_user_documents_container": self.personal,
                "cosmos_group_documents_container": self.groups,
                "cosmos_public_documents_container": self.public,
                "assert_document_available": access.assert_document_available,
                "document_provenance": access.document_provenance,
                "PROVENANCE_FIELD": access.PROVENANCE_FIELD,
            },
        )
        self.hold()
        with self.assertRaises(DocumentHeldError):
            namespace["_resolve_chat_selected_document_metadata"]("document-1", user_id="user-1")


class NativeCacheBoundaryTests(ScreeningAccessFixture):
    def plugin(self):
        path = APP_ROOT / "semantic_kernel_plugins" / "tabular_processing_plugin.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        original = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TabularProcessingPlugin")
        names = {
            "__init__", "_evict_screened_blob_cache", "_assert_blob_screening_access",
            "_download_tabular_blob_bytes", "_get_tabular_blob_version", "_get_workbook_metadata",
            "_read_tabular_blob_to_dataframe", "_list_tabular_blobs", "_resolve_blob_location_with_fallback",
        }
        original.body = [node for node in original.body if isinstance(node, ast.FunctionDef) and node.name in names]
        namespace = {
            "Optional": Optional, "List": List, "copy": SimpleNamespace(deepcopy=deepcopy),
            "pandas": SimpleNamespace(DataFrame=object),
            "has_request_context": lambda: False,
            "PRIVATE_CONTAINER": access.PRIVATE_CONTAINER,
            "PROVENANCE_FIELD": access.PROVENANCE_FIELD,
            "SCREENING_FIELD": "content_screening",
            "ScreeningConflictError": ScreeningConflictError,
            "ScreeningError": ScreeningError,
            "assert_blob_available": access.assert_blob_available,
            "document_provenance": access.document_provenance,
            "read_available_document_bytes": access.read_available_document_bytes,
            "resolve_available_blob_location": access.resolve_available_blob_location,
            "log_event": lambda *_args, **_kwargs: None,
            "logging": logging,
        }
        exec(compile(ast.Module(body=[original], type_ignores=[]), str(path), "exec"), namespace)
        plugin = namespace["TabularProcessingPlugin"](authorized_user_id="user-1")
        return plugin

    def test_byte_dataframe_and_workbook_cache_hits_all_read_fresh_metadata(self):
        for method in ("_download_tabular_blob_bytes", "_get_workbook_metadata", "_read_tabular_blob_to_dataframe"):
            with self.subTest(method=method):
                plugin = self.plugin()
                blob = self.document["content_screening"]["active_blob"]
                key = (blob["container"], blob["path"])
                plugin._screening_source_versions[key] = access.document_provenance(self.document)
                plugin._blob_data_cache[key] = b"PRIVATE CACHED BYTES"
                plugin._workbook_metadata_cache[key] = {"sheet_names": ["PRIVATE SHEET"]}
                plugin._df_cache[(*key, "__default__")] = "PRIVATE CACHED ROWS"
                self.hold()
                with self.assertRaises(DocumentHeldError):
                    getattr(plugin, method)(*key)
                self.assertEqual(plugin._blob_data_cache, {})
                self.assertEqual(plugin._workbook_metadata_cache, {})
                self.assertEqual(plugin._df_cache, {})
        self.assertEqual(self.blob_requests, [])

    def test_clean_replacement_cannot_reuse_the_previous_native_byte_cache(self):
        plugin = self.plugin()
        blob = self.document["content_screening"]["active_blob"]
        key = (blob["container"], blob["path"])
        plugin._screening_source_versions[key] = access.document_provenance(self.document)
        plugin._blob_data_cache[key] = b"OLD REMOVED VALUE"
        self.document["content_screening"]["availability_generation"] += 1
        with self.assertRaises(ScreeningConflictError):
            plugin._download_tabular_blob_bytes(*key)
        self.assertEqual(plugin._blob_data_cache, {})

    def test_private_storage_enumeration_stops_before_blob_io(self):
        plugin = self.plugin()
        with self.assertRaises(PermissionError):
            plugin._list_tabular_blobs("content-screening", "user-1/")
        self.assertEqual(self.blob_requests, [])

    def test_remembered_native_location_cannot_fall_back_after_hold(self):
        plugin = self.plugin()
        plugin._resolve_authorized_scope_arguments = lambda *_args, **_kwargs: {
            "user_id": "user-1", "conversation_id": "conversation-1",
            "group_id": None, "public_workspace_id": None,
        }
        plugin._get_resolved_blob_location_override = lambda *_args: ("user-documents", "user-1/original.txt")
        plugin._is_authorized_blob_location = lambda *_args: True
        self.hold()
        with self.assertRaises(DocumentHeldError):
            plugin._resolve_blob_location_with_fallback("user-1", "conversation-1", "original.txt", "workspace")
        self.assertEqual(self.blob_requests, [])


class ResumedEvidenceBoundaryTests(ScreeningAccessFixture):
    def test_cached_native_status_does_not_republish_or_expose_held_previews(self):
        run = {
            "id": "run-1", "user_id": "user-1", "conversation_id": "conversation-1",
            "status": "completed", "generated_artifact": {"preview_text": "PRIVATE PREVIEW"},
            "screening_sources": [{access.PROVENANCE_FIELD: access.document_provenance(self.document)}],
        }
        reconciled = []
        namespace = {
            "cosmos_conversations_container": self.conversations,
            "cosmos_tabular_export_runs_container": FakeContainer({"run-1": run}),
            "get_settings": lambda: {},
            "CosmosResourceNotFoundError": KeyError,
            "ScreeningError": ScreeningError,
            "assert_evidence_available": access.assert_evidence_available,
            "assert_blob_available": access.assert_blob_available,
            "_can_cancel_run": lambda _run: False,
            "_reconcile_completed_tabular_artifact_set": lambda _run: reconciled.append(True),
        }
        load_functions(
            "functions_tabular_generated_exports.py",
            {"_authorize_tabular_export_run_execution", "_screened_run_public_status", "get_tabular_generated_output_run_status"},
            namespace,
        )
        self.hold()
        status = namespace["get_tabular_generated_output_run_status"]("user-1", "run-1")
        self.assertFalse(status["source_available"])
        self.assertEqual(status["generated_artifacts"], [])
        self.assertFalse(status["can_resume"])
        self.assertNotIn("PRIVATE", json.dumps(status))
        self.assertEqual(reconciled, [])

    def test_linked_history_uses_clean_text_instead_of_original_attachment_metadata(self):
        self.modules["functions_documents"].get_ordered_document_chunks = lambda *_args, **_kwargs: [self.search_result()]
        namespace = load_functions(
            "route_backend_chats.py", {"_refresh_workspace_linked_history_message"},
            {
                "get_current_user_id": lambda: "user-1",
                "refresh_workspace_attachment": access.refresh_workspace_attachment,
                "assert_document_available": access.assert_document_available,
                "assert_document_chunks_available": access.assert_document_chunks_available,
                "document_provenance": access.document_provenance,
                "PROVENANCE_FIELD": access.PROVENANCE_FIELD,
            },
        )
        result = namespace["_refresh_workspace_linked_history_message"]({
            "role": "image", "workspace_document_id": "document-1",
            "file_content": "ORIGINAL PRIVATE TEXT", "extracted_text": "ORIGINAL PRIVATE TEXT",
            "vision_analysis": {"text": "ORIGINAL PRIVATE TEXT"},
        })
        self.assertEqual(result["file_content"], "Clean approved text")
        self.assertEqual(result["vision_analysis"], {})
        self.assertEqual(result["role"], "file")
        self.assertIn(access.PROVENANCE_FIELD, result)

    def test_persisted_native_run_rechecks_sources_before_reusing_staged_rows(self):
        namespace = {
            "cosmos_conversations_container": self.conversations,
            "CosmosResourceNotFoundError": KeyError,
            "assert_evidence_available": access.assert_evidence_available,
            "assert_blob_available": access.assert_blob_available,
            "storage_account_personal_chat_container_name": "personal-chat",
            "storage_account_user_documents_container_name": "user-documents",
            "storage_account_group_documents_container_name": "group-documents",
            "storage_account_public_documents_container_name": "public-documents",
        }
        load_functions("functions_tabular_generated_exports.py", {"_authorize_tabular_export_run_execution"}, namespace)
        run = {
            "user_id": "user-1", "conversation_id": "conversation-1",
            "screening_sources": [{access.PROVENANCE_FIELD: access.document_provenance(self.document)}],
        }
        self.hold()
        with self.assertRaises(DocumentHeldError):
            namespace["_authorize_tabular_export_run_execution"](run)

    def test_nested_historical_tool_provenance_is_not_lost_in_json(self):
        evidence = {
            "function_result": json.dumps({
                "document_id": "document-1",
                access.PROVENANCE_FIELD: access.document_provenance(self.document),
                "rows": [{"value": "previous result"}],
            }),
        }
        self.hold()
        with self.assertRaises(DocumentHeldError):
            access.assert_evidence_available(evidence, "user-1")

    def test_workspace_linked_file_provenance_is_checked_even_in_chat_scope(self):
        self.hold()
        evidence = {"scope": "chat", "document": {"workspace_document_id": "document-1", "source_type": "chat_upload"}}
        with self.assertRaises(DocumentHeldError):
            access.assert_evidence_available(evidence, "user-1")

    def test_stream_stops_emitting_after_a_new_hold_and_closes_provider_stream(self):
        source = {access.PROVENANCE_FIELD: access.document_provenance(self.document)}
        emitted = []
        closed = []

        class Service:
            async def _inner_get_streaming_chat_message_contents(inner_self):
                try:
                    yield "already sent"
                    self.hold()
                    yield "must be suppressed"
                finally:
                    closed.append(True)

        service = access.guard_chat_service(
            Service(), source_validator=lambda: access.assert_evidence_available(source, "user-1"),
        )

        async def consume():
            async for value in service._inner_get_streaming_chat_message_contents():
                emitted.append(value)

        with self.assertRaises(DocumentHeldError):
            asyncio.run(consume())
        self.assertEqual(emitted, ["already sent"])
        self.assertEqual(closed, [True])


class LegacyPreviewBoundaryTests(ScreeningAccessFixture):
    def preview_function(self, name):
        path = APP_ROOT / "route_frontend_chats.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
        node.decorator_list = []
        self.sas_calls = []

        def generate_sas(**kwargs):
            self.sas_calls.append(kwargs)
            raise AssertionError("A screened source must not enter the legacy SAS path")

        namespace = {
            "os": os, "request": request, "jsonify": jsonify,
            "get_current_user_id": lambda: "user-1",
            "get_document": lambda *_args: (jsonify(self.document), 200),
            "get_settings": lambda: {"enable_user_workspace": True},
            "assert_document_available": access.assert_document_available,
            "build_available_document_response": access.build_available_document_response,
            "ScreeningError": ScreeningError,
            "storage_account_user_documents_container_name": "user-documents",
            "generate_blob_sas": generate_sas,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        return namespace[name]

    def test_old_preview_aliases_serve_only_active_bytes_and_never_sign_originals(self):
        for name in ("view_pdf", "view_document"):
            with self.subTest(name=name):
                preview = self.preview_function(name)
                with self.app.test_request_context(f"/{name}?doc_id=document-1"):
                    response = preview()
                self.assertEqual(response.data, self.content)
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertEqual(self.sas_calls, [])
                self.assertNotIn("original.txt", response.headers["Content-Disposition"])

    def test_old_preview_aliases_deny_held_sources_before_blob_reads(self):
        self.hold()
        for name in ("view_pdf", "view_document"):
            with self.subTest(name=name):
                preview = self.preview_function(name)
                with self.app.test_request_context(f"/{name}?doc_id=document-1"):
                    _response, status = preview()
                self.assertEqual(status, 409)
                self.assertEqual(self.sas_calls, [])
        self.assertEqual(self.blob_requests, [])


if __name__ == "__main__":
    unittest.main()
