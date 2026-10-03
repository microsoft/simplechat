# test_saved_results_container_access_chat_orchestration.py
"""
Functional test for upload-only content screening in chat, Analyze and orchestration.
Version: 0.261.232
Implemented in: 0.261.232

This test ensures that saved and generated results take their access from their
container (the conversation or orchestration run) and are never hidden because a
source document was later deleted, re-uploaded or held for screening: saved Analyze
results, retained orchestration outputs, generated files, chat AI replies with their
stored citations, and conversation exports. It also ensures that a held uploaded
document is still refused whenever chat, search or an orchestration reads it as an
input, that the model fence still blocks a model call after such a read, and that
lineage and integrity failures are still refused. Refs #1621.

Cosmos, Blob, search and model I/O are doubled. No Azure resources are used.
"""

import ast
from collections import Counter, defaultdict
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from flask import jsonify

TESTS_ROOT = Path(__file__).resolve().parent
APP_ROOT = TESTS_ROOT.parent / "application" / "single_app"
for _path in (str(APP_ROOT), str(TESTS_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Application and fixture imports follow the standalone path setup.
from content_screening import access as screening_access  # noqa: E402
from content_screening.contracts import DocumentHeldError, ScreeningError  # noqa: E402
from functions_orchestration_result_contracts import ResultContractError  # noqa: E402
from functions_orchestration_results import ResultUnavailableError  # noqa: E402
from functions_workflow_result_store import WorkflowResultIntegrityError  # noqa: E402
from test_content_screening_access import FakeContainer, MissingDocument, ScreeningAccessFixture, fake_module  # noqa: E402
from test_support.app_stubs import import_app_module  # noqa: E402
from test_support.orchestration_results import ROWS, ResultFixture, source  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

saved = import_app_module("functions_saved_analysis")
analysis_access = import_app_module("functions_analysis_access")

SOURCE_CHANGES = ("deleted", "reuploaded", "held")
SAVED_SOURCE = {
    "document_id": "document-1", "scope": "group", "scope_id": "source-group",
    "source_version": "1", "source_revision": "etag-1", "authorization_status": "authorized",
}
REPLY = "The review found controls that still need an owner."


def load_body(file_name, function_name, namespace):
    """Execute one real application function against the supplied seams."""
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(APP_ROOT / file_name), "exec"), namespace)
    return namespace[function_name]


def test_current_version_includes_container_access():
    assert_app_version_at_least("0.261.232")


# --- Saved Analyze results --------------------------------------------------


class SourceState:
    """A source document that may be deleted, re-uploaded or held when it is resolved."""

    def __init__(self):
        self.change = None
        self.resolutions = 0

    def resolve(self, document_ids, **context):
        self.resolutions += 1
        if self.change == "held":
            raise DocumentHeldError()
        if self.change == "deleted":
            return [{**SAVED_SOURCE, "authorization_status": "unresolved"}]
        if self.change == "reuploaded":
            return [{**SAVED_SOURCE, "source_version": "2", "source_revision": "etag-2"}]
        return [dict(SAVED_SOURCE)]


class ChatSections:
    def __init__(self):
        self.contents = {}

    def save(self, user_id, conversation_id, message_id, section, **kwargs):
        payload = json.dumps(section, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
        self.contents[(user_id, conversation_id, message_id, digest)] = payload
        return {
            "storage": "cosmos", "schema_version": 1, "sha256": digest,
            "size_bytes": len(payload), "chunk_count": 1,
        }

    def load(self, user_id, conversation_id, message_id, reference):
        return json.loads(self.contents[(user_id, conversation_id, message_id, reference["sha256"])])

    def rewrite(self, reference, change):
        key = next(key for key in self.contents if key[3] == reference["sha256"])
        value = json.loads(self.contents[key])
        change(value)
        self.contents[key] = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class SavedChat:
    """A saved chat Analyze result, its assistant message and a generated projection."""

    def __init__(self, sources):
        self.sources = sources
        self.conversation_allowed = True
        self.store = ChatSections()
        result = {
            "reply": REPLY,
            "analysis_result": {
                "analysis_result_version": "analyze-final-v1",
                "analysis_reply": f"## Findings\n\n{REPLY}",
                "source_manifest": [dict(SAVED_SOURCE)],
                "authoritative_result": {
                    "kind": "records",
                    "value": [{
                        "record_id": f"record-{index}", "document_id": "document-1",
                        "source": {"file_name": "controls.txt"},
                        "values": {"control": f"Control {index}", "finding": "Owner unassigned"},
                        "evidence_refs": [f"evidence-{index}"],
                    } for index in range(3)],
                },
                "analysis_evidence": [{
                    "evidence_id": f"evidence-{index}", "document_id": "document-1",
                    "file_name": "controls.txt", "page_number": index + 1, "quote": "Owner: unassigned",
                } for index in range(3)],
                "analysis_validation": {"status": "valid", "limitations": []},
            },
        }
        self.descriptor = saved.save_chat_analysis(
            result, user_id="owner", conversation_id="conversation-1", message_id="assistant-1",
            authorize_conversation=self.authorize, save_result=self.store.save,
            source_resolver=sources.resolve,
        )
        self.message = {
            "id": "assistant-1", "conversation_id": "conversation-1", "role": "assistant",
            "content": REPLY, "metadata": {"saved_analysis": self.descriptor},
            "hybrid_citations": [{"document_id": "document-1", "chunk_text": "Owner: unassigned"}],
            "agent_citations": [{"function_result": "STORED_TOOL_CITATION"}],
        }
        self.context = saved.saved_analysis_context(self.descriptor)

    def authorize(self, user_id, conversation_id):
        if user_id not in ("owner", "reader") or conversation_id != "conversation-1" or not self.conversation_allowed:
            raise PermissionError("Conversation access was removed.")
        return {"id": conversation_id, "user_id": "owner"}

    def load_message(self, user_id, conversation_id, message_id):
        self.authorize(user_id, conversation_id)
        if message_id != "assistant-1":
            raise LookupError("Message not found.")
        return self.message

    def read_options(self):
        return {
            "message_loader": self.load_message, "chat_loader": self.store.load,
            "source_resolver": self.sources.resolve,
        }

    def read(self, context=None):
        return saved.load_saved_analysis("reader", context or self.context, **self.read_options())

    def artifact(self):
        return {
            "id": "artifact-1", "conversation_id": "conversation-1", "role": "file",
            "metadata": saved.analysis_artifact_metadata({
                "kind": "chat", "conversation_id": "conversation-1", "message_id": "assistant-1",
            }),
        }

    def authorize_artifact(self, **kwargs):
        return saved.authorize_analysis_artifact(
            "reader", self.artifact(), parents_loader=lambda *args: [self.message],
            result_reader=lambda user_id, context: self.read(context), **kwargs,
        )


@pytest.mark.parametrize("when", ["before_save", "after_save"])
@pytest.mark.parametrize("change", SOURCE_CHANGES)
def test_saved_analyze_results_keep_conversation_access_when_a_source_changes(change, when):
    sources = SourceState()
    if when == "before_save":
        sources.change = change
    chat = SavedChat(sources)
    sources.change = change
    original = deepcopy(chat.message)

    manifest, _, checked = chat.read()
    page = saved.read_saved_analysis_page("reader", chat.context, **chat.read_options())
    evidence = saved.read_saved_analysis_page(
        "reader", chat.context, representation="evidence", record_id="record-1", **chat.read_options(),
    )
    explanation, descriptor = saved.load_saved_analysis_input("reader", chat.context, **chat.read_options())
    history = saved.sanitize_saved_analysis_messages(
        [chat.message], "reader", result_reader=lambda user_id, context: chat.read(context),
    )
    chat.authorize_artifact()
    chat.authorize_artifact(for_publication=True)

    assert manifest["identity"]["message_id"] == "assistant-1"
    assert checked["source_count"] == 1 and checked["source_snapshot_changed"] is False
    assert page["total_records"] == 3
    assert [item["evidence_id"] for item in evidence["evidence"]] == ["evidence-1"]
    assert '"original_sources_reanalyzed": false' in explanation and "Control 2" in explanation
    assert descriptor["result_sha256"] == chat.descriptor["result_sha256"]
    assert history[0]["content"] == REPLY
    assert history[0]["hybrid_citations"] == original["hybrid_citations"]
    assert history[0]["agent_citations"] == original["agent_citations"]
    assert history[0]["metadata"]["saved_analysis"].get("available") is not False
    assert sources.resolutions == 0


def test_saved_analyze_results_still_refuse_container_and_integrity_failures():
    sources = SourceState()
    chat = SavedChat(sources)

    with pytest.raises(ValueError, match="changed"):
        chat.read({**chat.context, "result_sha256": "0" * 64})

    chat.store.rewrite(chat.descriptor["result_ref"], lambda manifest: manifest["identity"].update(message_id="other"))
    with pytest.raises(analysis_access.AnalysisResultUnavailable) as lineage:
        chat.read()
    assert lineage.value.code == "analysis_lineage_invalid"

    chat.store.rewrite(chat.descriptor["result_ref"], lambda manifest: manifest["identity"].update(message_id="assistant-1"))
    chat.store.rewrite(chat.descriptor["result_ref"], lambda manifest: manifest["analysis_access"].update(sources=[]))
    with pytest.raises(analysis_access.AnalysisResultUnavailable) as provenance:
        chat.read()
    assert provenance.value.code == "analysis_source_manifest_missing"

    chat.conversation_allowed = False
    with pytest.raises(PermissionError):
        chat.read()
    with pytest.raises(PermissionError):
        chat.authorize_artifact()
    history = saved.sanitize_saved_analysis_messages(
        [chat.message], "reader", result_reader=lambda user_id, context: chat.read(context),
    )
    assert history[0]["content"] == saved.UNAVAILABLE_ANALYSIS_MESSAGE
    assert history[0]["agent_citations"] == [] and "STORED_TOOL_CITATION" not in json.dumps(history)
    assert sources.resolutions == 0


# --- Retained orchestration outputs ----------------------------------------------


def _change_orchestration_source(fixture, change):
    if change == "deleted":
        fixture.sources.clear()
    elif change == "reuploaded":
        fixture.sources["document-1"]["source_version"] = 2
        fixture.sources["document-1"]["source_revision"] = "revision-2"
    else:
        fixture.held.add("document-1")


@pytest.mark.parametrize("when", ["before_save", "after_save"])
@pytest.mark.parametrize("change", SOURCE_CHANGES)
def test_orchestration_outputs_keep_run_access_when_a_source_changes(change, when):
    fixture = ResultFixture()
    if when == "before_save":
        _change_orchestration_source(fixture, change)
    task = fixture.save()
    if when == "after_save":
        _change_orchestration_source(fixture, change)
    reader = fixture.restart().open_result(task.output("findings"), require_current_sources=True)
    rows = list(reader.iter_records())
    reader.recheck()
    assert rows == ROWS
    assert reader.metadata()["source_count"] == 1
    assert fixture.source_reads == []


def test_orchestration_outputs_still_refuse_container_and_integrity_failures():
    fixture = ResultFixture()
    reference = fixture.save().output("findings")
    fixture.held.add("document-1")
    store = fixture.service.store
    producer = reference.producer
    arguments = (producer.user_id, producer.conversation_id, producer.run_id, producer.step_id)
    uncommitted = store.save_orchestration(
        *arguments, {"private": "uncommitted"}, guard_token="server-attempt-token", require_analysis_guard=True,
    )
    with pytest.raises(WorkflowResultIntegrityError):
        fixture.service.open_result(reference.__class__.from_dict({
            **reference.to_dict(), "manifest_sha256": uncommitted["sha256"],
        }))
    corrupt = reference.__class__.from_dict({**reference.to_dict(), "content_sha256": "0" * 64})
    with pytest.raises(ResultContractError):
        fixture.service.open_result(corrupt)

    fixture.conversation["orchestration_deleted"] = True
    with pytest.raises(ResultUnavailableError):
        fixture.restart().open_result(reference)
    fixture.conversation.pop("orchestration_deleted")
    fixture.runs["run-1"]["checkpoints_deleted"] = True
    with pytest.raises(ResultUnavailableError):
        fixture.restart().open_result(reference)
    assert fixture.source_reads == []


@pytest.mark.parametrize("change", ["deleted", "held"])
def test_orchestration_still_checks_uploaded_documents_it_reads_as_inputs(change):
    fixture = ResultFixture()
    _change_orchestration_source(fixture, change)
    with pytest.raises((ScreeningError, PermissionError, LookupError)):
        fixture.service.access.authorize_input_sources([source()], require_snapshot=True)
    assert fixture.source_reads


# --- Chat history, exports, generated files and input reads ------------------------


class ContainerAccessAndInputReadTests(ScreeningAccessFixture):
    def setUp(self):
        super().setUp()
        self.telemetry = patch.dict(sys.modules, {
            "functions_appinsights": fake_module(
                "functions_appinsights", log_event=lambda *args, **kwargs: None,
                debug_print=lambda *args, **kwargs: None,
            ),
        })

    def change_source(self, change):
        if change == "held":
            self.hold()
        elif change == "deleted":
            self.documents.pop("document-1")
        else:
            self.document["version"] = 3
            self.document["content_screening"]["source_revision"] = "3"
            self.seed_release(self.document)

    def provenance(self):
        return {screening_access.PROVENANCE_FIELD: screening_access.document_provenance(self.document)}

    def assistant_reply(self):
        return {
            "id": "assistant-message", "conversation_id": "conversation-1", "role": "assistant",
            "content": REPLY,
            "hybrid_citations": [{
                "document_id": "document-1", "version": 2, "file_name": "reviewed.txt",
                "chunk_text": "STORED_DOCUMENT_CITATION",
            }],
            "agent_citations": [{
                "plugin_name": "BlobStoragePlugin", "function_name": "read_file_content", "success": True,
                "function_arguments": {"blob_name": self.document["content_screening"]["active_blob"]["path"]},
                "function_result": {
                    "container_name": "user-documents",
                    "blob_name": self.document["content_screening"]["active_blob"]["path"],
                    "content": "STORED_TOOL_CITATION",
                },
            }],
            "metadata": {"screening_sources": [self.provenance()]},
        }

    def workspace_attachment(self):
        return {
            "id": "file-message", "conversation_id": "conversation-1", "role": "file",
            "workspace_document_id": "document-1",
            "file_content": "ATTACHMENT_TEXT", "extracted_text": "ATTACHMENT_TEXT",
        }

    def generated_artifact(self, **changes):
        return {
            "id": "artifact-1", "conversation_id": "conversation-1", "role": "file",
            "file_content_source": "blob", "blob_container": "personal-chat",
            "blob_path": "user-1/conversation-1/generated/artifact-1/report.md", "filename": "report.md",
            "metadata": {"is_generated_chat_artifact": True, "screening_sources": [self.provenance()]},
            **changes,
        }

    def chat_artifact_authorizer(self, message):
        return load_body("route_enhanced_citations.py", "_get_authorized_chat_artifact_message", {
            "cosmos_conversations_container": self.conversations,
            "cosmos_messages_container": FakeContainer({message["id"]: message}),
            "CosmosResourceNotFoundError": MissingDocument,
            "build_conversation_participation_context": self.authorize_conversation,
            "assert_generated_file_approval_allows_download": lambda user_id, item: None,
            "assert_generated_chat_artifact_is_published_for_user": lambda user_id, item: None,
            "assert_document_available": screening_access.assert_document_available,
            "assert_evidence_available": screening_access.assert_evidence_available,
        })

    def export(self, messages):
        namespace = {
            "Any": Any, "Dict": Dict, "List": List, "Mapping": Mapping,
            "Counter": Counter, "defaultdict": defaultdict,
            "TRANSCRIPT_ROLES": {"user", "assistant"},
            "build_message_artifact_payload_map": lambda raw_messages: {},
            "_filter_messages_for_export": list,
            "sanitize_saved_analysis_messages": saved.sanitize_saved_analysis_messages,
            "hydrate_agent_citations_from_artifacts": lambda raw_messages, payloads: raw_messages,
            "public_history_messages": screening_access.public_history_messages,
            "sort_messages_by_thread": list,
            "is_collaboration_conversation": lambda conversation: False,
            "get_thoughts_for_conversation": lambda *args: [],
            "get_accessible_collaboration_message_thoughts": lambda *args: [],
            "_sanitize_thought": deepcopy,
            "_sanitize_message": lambda message, **kwargs: deepcopy(message),
            "_sanitize_conversation": lambda conversation, **kwargs: conversation,
            "_build_summary_intro": lambda **kwargs: None,
        }
        load_body("functions_saved_analysis.py", "is_saved_analysis_unavailable", namespace)
        build = load_body("route_backend_conversation_export.py", "_build_export_entry", namespace)
        return build({"id": "conversation-1"}, messages, "user-1", {})["messages"]

    def test_chat_replies_citations_and_exports_survive_source_changes(self):
        for change in SOURCE_CHANGES:
            with self.subTest(change=change):
                self.setUp()
                self.modules["functions_documents"].get_ordered_document_chunks = (
                    lambda *args, **kwargs: [self.search_result(version=self.document["version"])]
                )
                reply = self.assistant_reply()
                attachment = self.workspace_attachment()
                self.change_source(change)
                reads_before = self.personal.reads["document-1"]
                history = screening_access.public_history_messages([deepcopy(reply)], "user-1")
                self.assertEqual(self.personal.reads["document-1"], reads_before)
                exported = {message["id"]: message for message in self.export([deepcopy(reply), attachment])}
                for message in (history[0], exported["assistant-message"]):
                    self.assertEqual(message["content"], REPLY)
                    self.assertNotIn("content_unavailable", message)
                    self.assertEqual(message["hybrid_citations"], reply["hybrid_citations"])
                    self.assertIn("STORED_TOOL_CITATION", json.dumps(message["agent_citations"]))
                file_message = exported["file-message"]
                if change == "reuploaded":
                    self.assertEqual(file_message["file_content"], "Clean approved text")
                else:
                    self.assertTrue(file_message["content_unavailable"])
                    self.assertNotIn("ATTACHMENT_TEXT", json.dumps(file_message))

    def test_model_history_replays_stored_replies_without_rechecking_their_sources(self):
        evidence_checks = []
        helper = load_body("route_backend_chats.py", "build_assistant_history_content_with_citations", {
            "assert_evidence_available": lambda *args, **kwargs: evidence_checks.append(args),
            "_build_agent_citation_history_lines": lambda citations: [json.dumps(citations)],
            "_build_document_citation_history_lines": lambda citations: [json.dumps(citations)],
            "_build_web_citation_history_lines": lambda citations: [],
            "_truncate_history_citation_text": lambda text, max_chars: text,
        })
        self.hold()
        content = helper(self.assistant_reply(), REPLY)
        self.assertIn(REPLY, content)
        self.assertIn("STORED_TOOL_CITATION", content)
        self.assertEqual(evidence_checks, [])
        self.assertEqual(self.personal.reads["document-1"], 0)

    def test_generated_chat_files_take_conversation_access_not_source_access(self):
        for change in SOURCE_CHANGES:
            with self.subTest(change=change):
                self.setUp()
                artifact = self.generated_artifact()
                self.change_source(change)
                self.assertEqual(self.chat_artifact_authorizer(artifact)("user-1", "conversation-1", "artifact-1")["id"], "artifact-1")
        self.setUp()
        with self.assertRaises(PermissionError):
            self.chat_artifact_authorizer(self.generated_artifact())("user-2", "conversation-1", "artifact-1")
        with self.assertRaises(LookupError):
            self.chat_artifact_authorizer(self.generated_artifact(file_content_source="workspace"))(
                "user-1", "conversation-1", "artifact-1",
            )

    def test_held_upload_is_still_refused_when_read_as_an_input(self):
        self.modules["functions_documents"].get_chat_upload_workspace_documents_for_conversation = (
            lambda user_id, conversation_id: [deepcopy(self.document)]
        )
        namespace = {
            "DOCUMENT_ACTION_TYPE_NONE": "none",
            "debug_print": lambda *args, **kwargs: None,
            "_assigned_knowledge_allows_document_action": lambda filters, action: True,
            "assert_document_available": screening_access.assert_document_available,
            "ScreeningError": ScreeningError,
            "_is_search_ready_chat_upload_workspace_document": lambda document: True,
            "_get_chat_upload_workspace_document_scope": lambda document: "personal",
        }
        load_body("route_backend_chats.py", "_normalize_conversation_task_document_ids", namespace)
        select_documents = load_body("route_backend_chats.py", "_resolve_conversation_task_documents", namespace)
        open_citation = load_body("route_enhanced_citations.py", "get_document", {
            "get_settings": lambda: {"enable_user_workspace": True},
            "get_user_groups": lambda user_id: [],
            "get_user_visible_public_workspace_ids_from_settings": lambda user_id: [],
            "get_document_record": lambda user_id, doc_id, **scope: (
                deepcopy(self.documents[doc_id]) if doc_id in self.documents else None
            ),
            "assert_document_available": screening_access.assert_document_available,
            "ScreeningError": ScreeningError, "jsonify": jsonify,
        })
        with self.app.test_request_context():
            self.assertEqual(open_citation("user-1", "document-1")[1], 200)
        self.assertEqual(
            select_documents(user_id="user-1", conversation_id="conversation-1")["document_ids"], ["document-1"],
        )
        self.assertEqual(len(screening_access.filter_available_results([self.search_result()], "user-1")), 1)

        self.hold()
        self.assertEqual(screening_access.filter_available_results([self.search_result()], "user-1"), [])
        selected = select_documents(user_id="user-1", conversation_id="conversation-1")
        self.assertEqual((selected["document_ids"], selected["pending_document_ids"]), ([], ["document-1"]))
        with self.assertRaises(DocumentHeldError):
            select_documents(user_id="user-1", conversation_id="conversation-1", candidate_document_ids=["document-1"])
        with self.app.test_request_context():
            response, status = open_citation("user-1", "document-1")
            self.assertNotEqual(status, 200)
            self.assertEqual(response.get_json()["error_code"], DocumentHeldError.code)
        with self.assertRaises(DocumentHeldError):
            screening_access.read_available_document_bytes("document-1", "user-1", purpose="preview")
        with self.assertRaises(DocumentHeldError):
            self.chat_artifact_authorizer(self.generated_artifact(workspace_document_id="document-1"))(
                "user-1", "conversation-1", "artifact-1",
            )
        history = screening_access.public_history_messages([self.workspace_attachment()], "user-1")
        self.assertTrue(history[0]["content_unavailable"])
        self.assertNotIn("ATTACHMENT_TEXT", json.dumps(history))

    def test_only_a_held_input_read_closes_the_model_fence(self):
        self.hold()
        calls = []
        with self.app.test_request_context():
            history = screening_access.public_history_messages([self.assistant_reply()], "user-1")
            self.assertEqual(history[0]["content"], REPLY)
            answer = screening_access.guard_model_callable(lambda: calls.append("replayed") or "ok", [], "user-1")
            self.assertEqual(answer(), "ok")
            with self.assertRaises(DocumentHeldError):
                screening_access.assert_document_available("document-1", "user-1", purpose="chat_file")
            blocked = screening_access.guard_model_callable(lambda: calls.append("after_input"), [], "user-1")
            with self.assertRaises(DocumentHeldError):
                blocked()
        self.assertEqual(calls, ["replayed"])

    def test_a_caught_held_input_read_still_blocks_a_headless_model_call(self):
        self.hold()
        calls = []
        with self.telemetry, self.assertRaises(DocumentHeldError):
            with screening_access.strict_source_authority():
                try:
                    screening_access.assert_document_available("document-1", "user-1", purpose="orchestration")
                except DocumentHeldError:
                    pass
                screening_access.guard_model_callable(lambda: calls.append("model"), [], "user-1")()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
