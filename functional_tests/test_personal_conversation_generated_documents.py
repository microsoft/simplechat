#!/usr/bin/env python3
# test_personal_conversation_generated_documents.py
"""
Functional test for listing and downloading documents agents created in a personal conversation.
Version: 0.261.302
Implemented in: 0.261.302

This test ensures that the personal conversation routes behind the V2 Documents drawer's Generated
section list the documents SimpleChat upload actions created only from messages the thread shows.
Deleted messages, replaced thread attempts, hidden generated chat files and masked messages are
left out, and a citation stored in compact form is rebuilt from its artifact record before it is
read. It also checks that both routes require login and the conversation's owner before anything is
read, and that the download route only serves a document this conversation produced, under the
workspace's own download rules. Neither route may return exception text to the browser
(CodeQL py/stack-trace-exposure).
"""

import ast
import contextlib
import importlib
import json
import os
import sys
import types

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
ROUTE_FILE = os.path.join(APP_DIR, "route_backend_conversations.py")
IMPLEMENTED_IN_VERSION = "0.261.302"
CONVERSATION_ID = "conv-personal-1"
DOC_WORD = "11111111-2222-3333-4444-555555555555"
DOC_DECK = "22222222-3333-4444-5555-666666666666"
DOC_DELETED = "33333333-4444-5555-6666-777777777777"
DOC_OLD_ATTEMPT = "44444444-5555-6666-7777-888888888888"
DOC_MASKED = "55555555-6666-7777-8888-999999999999"
DOC_HIDDEN_FILE = "66666666-7777-8888-9999-000000000000"
LIST_ROUTE = "list_personal_conversation_generated_documents_api"
DOWNLOAD_ROUTE = "download_personal_conversation_generated_document_api"
HELPER = "_list_personal_conversation_generated_documents"
SAFE_EXCEPTION_ATTRIBUTES = {"public_message", "code", "status_code"}


def route_module_ast():
    with open(ROUTE_FILE, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read())


def functions_named(*names):
    found = {
        node.name: node for node in ast.walk(route_module_ast())
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    assert set(found) == set(names), sorted(found)
    return found


@contextlib.contextmanager
def real_helper_modules():
    """Import the real message and generated-document helpers, faking only their heavy dependencies."""
    names = [
        "config",
        "functions_azure_maps",
        "functions_documents",
        "functions_group",
        "functions_settings",
        "functions_message_artifacts",
        "functions_message_deletion",
        "functions_collaboration_generated_documents",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    sys.path.insert(0, APP_DIR)
    try:
        azure_maps = types.ModuleType("functions_azure_maps")
        azure_maps.refresh_azure_maps_citation_payload = lambda payload: payload
        documents = types.ModuleType("functions_documents")
        documents.get_document_record = lambda **_kwargs: None
        group = types.ModuleType("functions_group")
        group.assert_group_role = lambda *_args, **_kwargs: "Owner"
        group.find_group_by_id = lambda _group_id: None
        settings = types.ModuleType("functions_settings")
        settings.get_settings = lambda: {}
        settings.is_group_workspace_file_download_enabled = lambda _settings, _group: False
        settings.is_personal_workspace_file_download_enabled = lambda _settings: False
        sys.modules.update({
            "functions_azure_maps": azure_maps,
            "functions_documents": documents,
            "functions_group": group,
            "functions_settings": settings,
        })
        for name in ("functions_message_artifacts", "functions_message_deletion",
                     "functions_collaboration_generated_documents"):
            sys.modules.pop(name, None)
        yield (
            importlib.import_module("functions_message_artifacts"),
            importlib.import_module("functions_message_deletion"),
            importlib.import_module("functions_collaboration_generated_documents"),
        )
    finally:
        sys.path.remove(APP_DIR)
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class FakeMessagesContainer:
    """The conversation's messages, with the queries the helper made."""

    def __init__(self, items):
        self.items = items
        self.queries = []

    def query_items(self, query, parameters=None, partition_key=None, **_kwargs):
        self.queries.append({"query": query, "parameters": parameters, "partition_key": partition_key})
        return list(self.items)


def upload_citation(document_id, file_name, function_name="upload_word_document", **extra):
    return {
        "plugin_name": "SimpleChatPlugin",
        "function_name": function_name,
        "timestamp": "2026-10-08T12:00:00Z",
        "function_result": {
            "success": True,
            "document": {"id": document_id, "file_name": file_name},
            "workspace_scope": "personal",
        },
        **extra,
    }


def assistant(message_id, timestamp, citations, **metadata):
    return {
        "id": message_id,
        "conversation_id": CONVERSATION_ID,
        "role": "assistant",
        "timestamp": timestamp,
        "content": "Done.",
        "agent_citations": citations,
        "metadata": {"thread_info": {"active_thread": True}, **metadata},
    }


def build_helper(container, log):
    """The real helper's source, run against the fake container and the real collaborators."""
    helper = functions_named(HELPER)[HELPER]
    module = ast.Module(body=[helper], type_ignores=[])
    namespace = {}
    with real_helper_modules() as (artifacts, deletion, generated):
        namespace.update({
            "cosmos_messages_container": container,
            "exclude_soft_deleted_messages": deletion.exclude_soft_deleted_messages,
            "build_message_artifact_payload_map": artifacts.build_message_artifact_payload_map,
            "filter_assistant_artifact_items": artifacts.filter_assistant_artifact_items,
            "hydrate_agent_citations_from_artifacts": artifacts.hydrate_agent_citations_from_artifacts,
            "collect_generated_documents": generated.collect_generated_documents,
            "log_event": lambda message, **kwargs: log.append((message, kwargs)),
        })
        exec(compile(module, ROUTE_FILE, "exec"), namespace)
    return namespace[HELPER]


def test_only_documents_the_thread_shows_are_listed():
    print("Testing which messages the personal list reads...")
    deck = upload_citation(DOC_DECK, "Quarterly review.pptx", "upload_powerpoint_document")
    compact = {
        "tool_name": "upload_powerpoint_document",
        "function_name": "upload_powerpoint_document",
        "plugin_name": "SimpleChatPlugin",
        "function_result": {"success": True, "document": "{…}"},
        "artifact_id": "artifact-deck",
        "raw_payload_externalized": True,
    }
    items = [
        {"id": "u-1", "conversation_id": CONVERSATION_ID, "role": "user", "timestamp": "2026-10-08T11:59:00Z",
         "content": "Write the brief and the deck.", "metadata": {}},
        # Stored out of order on purpose: the list follows the conversation, not storage order.
        assistant("a-2", "2026-10-08T12:02:00Z", [compact]),
        assistant("a-1", "2026-10-08T12:01:00Z", [upload_citation(DOC_WORD, "Watch brief.docx")]),
        {"id": "artifact-deck", "conversation_id": CONVERSATION_ID, "role": "assistant_artifact",
         "content": json.dumps({"citation": deck}), "metadata": {}},
        assistant("a-deleted", "2026-10-08T12:03:00Z", [upload_citation(DOC_DELETED, "Deleted.docx")], is_deleted=True),
        assistant("a-old", "2026-10-08T12:04:00Z", [upload_citation(DOC_OLD_ATTEMPT, "Old attempt.docx")],
                  thread_info={"active_thread": False}),
        assistant("a-masked", "2026-10-08T12:05:00Z", [upload_citation(DOC_MASKED, "Masked.md", "upload_markdown_document")],
                  masked=True),
        {**assistant("f-hidden", "2026-10-08T12:06:00Z", [upload_citation(DOC_HIDDEN_FILE, "Hidden.docx")],
                     is_generated_chat_artifact=True), "role": "file"},
        assistant("a-legacy", "2026-10-08T12:07:00Z", [upload_citation(DOC_WORD, "Watch brief.docx")],
                  thread_info=None),
    ]
    container = FakeMessagesContainer(items)
    log = []
    listed = build_helper(container, log)({"id": CONVERSATION_ID, "user_id": "u-owner"})

    assert [entry["document_id"] for entry in listed] == [DOC_WORD, DOC_DECK], listed
    assert listed[0]["message_id"] == "a-1" and listed[0]["file_name"] == "Watch brief.docx"
    assert listed[1]["file_name"] == "Quarterly review.pptx", "a compact citation is rebuilt from its artifact record"
    assert all(entry["workspace_scope"] == "personal" for entry in listed)

    assert len(container.queries) == 1, container.queries
    query = container.queries[0]
    assert query["partition_key"] == CONVERSATION_ID, "only the authorized conversation's partition is read"
    assert query["parameters"] == [{"name": "@conversation_id", "value": CONVERSATION_ID}], query
    assert "@conversation_id" in query["query"] and CONVERSATION_ID not in query["query"], "the id is a parameter"
    assert log and log[0][1].get("debug_only") is True, "the listing is debug-logged only"
    print("  ok  deleted, replaced, masked and hidden messages are skipped; compact citations are rebuilt")


def test_routes_require_the_owner_before_reading():
    print("Testing the personal routes' access policy...")
    functions = functions_named(LIST_ROUTE, DOWNLOAD_ROUTE)
    expected_paths = {
        LIST_ROUTE: "/api/conversations/<conversation_id>/generated-documents",
        DOWNLOAD_ROUTE: "/api/conversations/<conversation_id>/generated-documents/<document_id>/download",
    }
    for name, node in functions.items():
        decorators = [ast.unparse(decorator) for decorator in node.decorator_list]
        assert decorators[0].startswith("bp.route("), (name, decorators)
        assert f"'{expected_paths[name]}'" in decorators[0] and "methods=['GET']" in decorators[0], decorators[0]
        assert decorators[1:] == ["swagger_route(security=get_auth_security())", "login_required", "user_required"], (
            name, decorators,
        )
        calls = {
            ast.unparse(call.func): call.lineno
            for call in sorted(
                (child for child in ast.walk(node) if isinstance(child, ast.Call)),
                key=lambda child: child.lineno,
                reverse=True,
            )
        }
        assert "get_current_user_id" in calls, name
        authorize_line = calls.get("_authorize_personal_conversation_read")
        read_line = calls.get(HELPER)
        assert authorize_line and read_line and authorize_line < read_line, (
            f"{name} must confirm the caller owns the conversation before reading its messages"
        )
        source = ast.unparse(node)
        assert "_authorize_personal_conversation_read(user_id, conversation_id)" in source, name
        assert "request." not in source, f"{name} takes no identity or scope from the request"

    list_source = ast.unparse(functions[LIST_ROUTE])
    assert "'group_id'" not in list_source, "the list does not reveal group ids"
    assert "can_download_generated_document(user_id, document, settings=settings)" in list_source

    download_source = ast.unparse(functions[DOWNLOAD_ROUTE])
    assert "candidate['document_id'] == document_id" in download_source, "only this conversation's documents are served"
    assert "authorize_generated_document_download(user_id, document)" in download_source
    assert "build_document_download_response(" in download_source

    helper_source = ast.unparse(functions_named(HELPER)[HELPER])
    assert "partition_key=conversation_id" in helper_source
    assert "conversation_item['id']" in helper_source, "the helper reads the authorized conversation's id"
    print("  ok  login, owner check first, scoped to the conversation's own documents")


def test_routes_never_return_exception_text():
    print("Testing that refusals and failures keep exception details in the server log...")
    for name, node in functions_named(LIST_ROUTE, DOWNLOAD_ROUTE).items():
        parents = {}
        for parent in ast.walk(node):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        caught = {
            handler.name for handler in ast.walk(node)
            if isinstance(handler, ast.ExceptHandler) and handler.name
        }
        assert caught, name
        responses = [
            call for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "jsonify"
        ]
        assert responses, name
        for call in responses:
            for child in ast.walk(call):
                if isinstance(child, ast.Name) and child.id in caught:
                    parent = parents.get(child)
                    # Only a screening error's own public sentence and code may reach the browser.
                    assert isinstance(parent, ast.Attribute) and parent.attr in SAFE_EXCEPTION_ATTRIBUTES, (
                        name, ast.unparse(call),
                    )
            assert "format_exc" not in ast.unparse(call), (name, ast.unparse(call))
        source = ast.unparse(node)
        for exposed in ("str(exc)", "str(e)", "repr(exc)", "str(error)"):
            assert exposed not in source, (name, exposed)
    print("  ok  every error response is a fixed message")


def test_client_reads_the_same_routes():
    print("Testing that the V2 client reads the personal routes...")
    client_file = os.path.join(ROOT_DIR, "application", "v2_ui", "src", "lib", "generatedDocuments.ts")
    with open(client_file, "r", encoding="utf-8") as handle:
        client_source = handle.read()
    assert "`/api/conversations/${encodeURIComponent(conversationId)}/generated-documents`" in client_source
    assert "/${encodeURIComponent(documentId)}/download" in client_source
    assert "kind === 'collaborative'" in client_source, "a shared conversation keeps its own routes"
    print("  ok  the drawer's personal list and download use these routes")


if __name__ == "__main__":
    assert_app_version_at_least(IMPLEMENTED_IN_VERSION)
    tests = [
        test_only_documents_the_thread_shows_are_listed,
        test_routes_require_the_owner_before_reading,
        test_routes_never_return_exception_text,
        test_client_reads_the_same_routes,
    ]
    for test in tests:
        test()
    print(f"\n{len(tests)} personal generated document checks passed")
