# test_content_screening_history.py
"""
Functional regressions for public history and native evidence quarantine.
Version: 0.261.122
Implemented in: 0.261.106

Executes the real history route, artifact hydration, and model-history guard
against fake Cosmos. Removed metadata aliases and missing release proofs must
not turn old source material into newly authorized evidence.
"""

import ast
from copy import deepcopy
import json
from types import SimpleNamespace
from typing import Any, Dict, List
import unittest

from flask import Blueprint, Response, jsonify, request
from werkzeug.test import Client

from test_content_screening_access import APP_ROOT, ScreeningAccessFixture
from content_screening import access
from content_screening.contracts import DocumentHeldError, ScreeningError


def load_body(file_name, function_name, namespace, *, nested=False):
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    candidates = ast.walk(tree) if nested else tree.body
    node = next(
        node for node in candidates
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(APP_ROOT / file_name), "exec"), namespace)
    return namespace[function_name]


class ScreeningHistoryTests(ScreeningAccessFixture):
    def native_citation(self, *, tabular=False):
        arguments = (
            {"source": "workspace", "filename": self.document["file_name"], "column": "email"}
            if tabular else {
                "blob_name": self.document["content_screening"]["active_blob"]["path"],
            }
        )
        return {
            "plugin_name": "TabularProcessingPlugin" if tabular else "BlobStoragePlugin",
            "function_name": "get_distinct_values" if tabular else "read_file_content",
            "success": True,
            "function_arguments": arguments,
            "function_result": (
                {"filename": self.document["file_name"], "values": ["TOOL_PRIVATE_CANARY"]}
                if tabular else {
                    "container_name": "user-documents", "blob_name": arguments["blob_name"],
                    "content": "TOOL_PRIVATE_CANARY",
                }
            ),
        }

    def test_legacy_native_evidence_is_not_source_free_history(self):
        for tabular in (False, True):
            with self.subTest(tabular=tabular):
                evidence = {"role": "assistant", "agent_citations": [self.native_citation(tabular=tabular)]}
                with self.assertRaises(ScreeningError):
                    access.assert_evidence_available(evidence, "user-1", cached=True)
        self.assertGreater(self.personal.reads["document-1"], 0)

    def test_unrelated_business_fields_do_not_become_native_workspace_references(self):
        access.assert_evidence_available({
            "function_name": "ExternalService.report",
            "function_result": json.dumps({"source": "public", "filename": "third-party-record"}),
        }, "user-1", cached=True)
        self.assertEqual(self.personal.reads["document-1"], 0)

    def test_known_native_results_can_use_their_matching_recorded_generation(self):
        evidence = {
            "role": "assistant", "agent_citations": [self.native_citation()],
            "metadata": {"screening_sources": [{
                access.PROVENANCE_FIELD: access.document_provenance(self.document),
            }]},
        }
        access.assert_evidence_available(evidence, "user-1", cached=True)
        self.hold()
        with self.assertRaises(DocumentHeldError):
            access.assert_evidence_available(evidence, "user-1", cached=True)

    def test_source_authorization_descriptor_cannot_bypass_a_hold(self):
        source = {
            "source_authorization": {
                "source": "workspace", "scope_id": "user-1", "container": "user-documents",
                "blob_path": self.document["content_screening"]["active_blob"]["path"],
            },
        }
        self.hold()
        with self.assertRaises(DocumentHeldError):
            access.assert_evidence_available(source, "user-1", cached=True)

    def test_real_model_history_helper_does_not_replay_held_native_values(self):
        helper = load_body("route_backend_chats.py", "build_assistant_history_content_with_citations", {
            "assert_evidence_available": access.assert_evidence_available,
            "_build_agent_citation_history_lines": lambda citations: [json.dumps(citations)],
            "_build_document_citation_history_lines": lambda citations: [],
            "_build_web_citation_history_lines": lambda citations: [],
        })
        self.hold()
        for tabular in (False, True):
            with self.subTest(tabular=tabular):
                with self.assertRaises(DocumentHeldError):
                    helper({"agent_citations": [self.native_citation(tabular=tabular)]}, "Previous answer")

    def test_history_api_suppresses_held_attachments_and_hydrated_tool_evidence(self):
        citation = self.native_citation()
        items = [
            {"id": "user-message", "role": "user", "content": "Preserve ordinary conversation text"},
            {"id": "file-message", "role": "file", "workspace_document_id": "document-1",
             "file_content": "ATTACHMENT_PRIVATE_CANARY", "extracted_text": "ATTACHMENT_PRIVATE_CANARY"},
            {"id": "assistant-message", "role": "assistant", "content": "SOURCE_DERIVED_CANARY",
             "agent_citations": [{"artifact_id": "artifact-one"}]},
        ]
        namespace = {
            "bp": Blueprint("screening_history", __name__),
            "swagger_route": lambda **kwargs: lambda function: function,
            "get_auth_security": lambda: [],
            "login_required": lambda function: function,
            "user_required": lambda function: function,
            "request": request, "jsonify": jsonify,
            "get_current_user_id": lambda: "user-1",
            "_authorize_personal_conversation_read": lambda actor, conversation: None,
            "debug_print": lambda *args, **kwargs: None,
            "cosmos_messages_container": SimpleNamespace(query_items=lambda **kwargs: deepcopy(items)),
            "build_message_artifact_payload_map": lambda messages: {"artifact-one": {"citation": citation}},
            "filter_assistant_artifact_items": lambda messages: messages,
            "hydrate_image_messages": lambda messages, **kwargs: messages,
            "public_history_messages": access.public_history_messages,
            "sanitize_saved_analysis_messages": lambda messages, _reader: messages,
            "hydrate_m365_pending_action_cards": lambda messages, _reader, _conversation: messages,
            "deepcopy": deepcopy, "List": List, "Dict": Dict, "Any": Any,
            "refresh_azure_maps_citation_payload": lambda value: value,
        }
        load_body("functions_message_artifacts.py", "hydrate_agent_citations_from_artifacts", namespace)
        load_body("route_backend_conversations.py", "api_get_messages", namespace, nested=True)
        self.app.register_blueprint(namespace["bp"])
        self.hold()
        response = Client(self.app, Response).get("/api/get_messages?conversation_id=conversation-one")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("Preserve ordinary conversation text", json.dumps(payload))
        self.assertNotIn("PRIVATE_CANARY", json.dumps(payload))
        self.assertNotIn("SOURCE_DERIVED_CANARY", json.dumps(payload))
        messages_by_id = {message["id"]: message for message in payload["messages"]}
        self.assertTrue(messages_by_id["file-message"]["content_unavailable"])
        self.assertTrue(messages_by_id["assistant-message"]["content_unavailable"])
        self.assertGreater(self.personal.reads["document-1"], 0)

    def test_screened_attachment_history_uses_only_current_clean_text(self):
        self.modules["functions_documents"].get_ordered_document_chunks = lambda *args, **kwargs: [self.search_result()]
        result = access.public_history_messages([{
            "id": "file-message", "role": "image", "workspace_document_id": "document-1",
            "file_content": "REMOVED_PRIVATE_TEXT", "extracted_text": "REMOVED_PRIVATE_TEXT",
            "blob_path": "reviewer-only-original", "metadata": {"vision_analysis": {"text": "REMOVED_PRIVATE_TEXT"}},
        }], "user-1")
        self.assertEqual(result[0]["file_content"], "Clean approved text")
        self.assertNotIn("REMOVED_PRIVATE_TEXT", json.dumps(result))
        self.assertNotIn("reviewer-only-original", json.dumps(result))

    def test_removed_search_metadata_aliases_are_replaced_before_provenance(self):
        self.document.update({"tags": ["allowed"], "document_classification": "Reviewed"})
        self.seed_release(self.document)
        stale = {
            **self.search_result(), "document_tags": ["REMOVED_PRIVATE_TAG"],
            "document_classification": "REMOVED_PRIVATE_CLASSIFICATION",
        }
        for result in (
            access.filter_available_results([stale], "user-1")[0],
            access.assert_document_chunks_available([stale], self.document, "user-1")[0],
        ):
            self.assertEqual(result["document_tags"], ["allowed"])
            self.assertEqual(result["document_classification"], "Reviewed")
            self.assertNotIn("REMOVED_PRIVATE", json.dumps(result))

    def test_public_metadata_is_status_only_without_matching_release_proof(self):
        self.scans.documents.clear()
        result = access.public_documents_payload([self.document], "user-1")[0]
        self.assertFalse(result["content_screening"]["available"])
        self.assertNotIn("abstract", result)
        self.seed_release(self.document)
        self.document["abstract"] = "UNAPPROVED_PRIVATE_ABSTRACT"
        result = access.public_document_payload(self.document)
        self.assertFalse(result["content_screening"]["available"])
        self.assertNotIn("UNAPPROVED_PRIVATE_ABSTRACT", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
