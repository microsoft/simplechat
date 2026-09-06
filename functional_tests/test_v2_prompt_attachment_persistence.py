# test_v2_prompt_attachment_persistence.py
#!/usr/bin/env python3
"""
Functional regression for prompt attachments at actual message persistence boundaries.
Version: 0.261.097
Implemented in: 0.261.096
Turn-reuse integration coverage expanded in: 0.261.097

Execute the shipping metadata helper, chat persistence statements, orchestration writer,
and shared post/stream routes against in-memory Cosmos containers. Importing the full chat
registrar would initialize Azure clients, so its original AST is compiled at the write
boundary instead. No production persistence statements are copied into this test.
"""

import ast
import inspect
import json
import logging
import random
import sys
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, Response, current_app, jsonify, request, session, stream_with_context

APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

# These pure application modules need the application import path, not app/config startup.
import collaboration_models  # noqa: E402
from functions_chat_stream_events import build_user_message_persisted_stream_event  # noqa: E402
from functions_prompt_metadata import build_prompt_selection_metadata  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_orchestration_conversation_context import load_modules  # noqa: E402


SEND_PATHS = ("chat", "chat-stream", "document-action", "orchestration", "shared-post", "shared-stream")
USER = {"user_id": "author-1", "display_name": "Author", "email": "author@example.test"}


class MemoryContainer:
    def __init__(self):
        self.rows = {}

    def upsert_item(self, document):
        self.rows[document["id"]] = deepcopy(document)
        return deepcopy(document)

    def read_item(self, item, partition_key):
        document = self.rows[item]
        assert partition_key == document.get("conversation_id", document["id"])
        return deepcopy(document)

    def query_items(self, **kwargs):
        assert kwargs["partition_key"]
        return [{"thread_id": "previous-thread"}]


@lru_cache(maxsize=None)
def _tree(filename):
    return ast.parse((APP_DIR / filename).read_text(encoding="utf-8"), filename=filename)


def _function(filename, name):
    matches = [
        node for node in ast.walk(_tree(filename))
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, f"Expected one {filename}:{name}"
    return matches[0]


def _load_functions(filename, namespace, *names):
    functions = [deepcopy(_function(filename, name)) for name in names]
    for function in functions:
        function.decorator_list = []
    exec(compile(ast.Module(body=functions, type_ignores=[]), filename, "exec"), namespace)


def _assigns(statement, name):
    return isinstance(statement, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == name for target in statement.targets
    )


def _is_message_write(statement):
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "upsert_item"
        and isinstance(statement.value.func.value, ast.Name)
        and statement.value.func.value.id == "cosmos_messages_container"
    )


def _execute_boundary(statements, namespace, return_name, events):
    wrapper = ast.parse("def exercise_boundary():\n    pass\n").body[0]
    wrapper.body = deepcopy(statements) + [ast.Return(value=ast.Name(id=return_name, ctx=ast.Load()))]
    module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    exec(compile(module, "<shipping-persistence-boundary>", "exec"), namespace)
    result = namespace["exercise_boundary"]()
    if not inspect.isgenerator(result):
        return result
    while True:
        try:
            events.append(next(result))
        except StopIteration as finished:
            return finished.value


def prompt_cases():
    base = {
        "id": "prompt-1", "name": "Status",
        "content": "Report on latency.",
        "original_content": "Report on {{topic}}.",
        "template_content": "Report on {{topic}}.",
        "composer_text": "Keep it brief.", "composer_embedded": False,
        "scope_type": "group", "scope_name": "Operations",
        "variables": {"topic": "latency"}, "edited": False, "user_text": "Keep it brief.",
    }
    return [
        ("appended", base, "Report on latency.\n\nKeep it brief."),
        ("prompt-only", {
            **base, "content": "Summarise the week.", "original_content": "Summarise the week.",
            "template_content": "Summarise the week.", "composer_text": "", "user_text": "",
            "variables": {},
        }, "Summarise the week."),
        ("composer", {
            **base, "content": "Summarise quarterly numbers.",
            "original_content": "Summarise {{composer}}.",
            "template_content": "Summarise {{composer}}.", "composer_text": "quarterly numbers",
            "composer_embedded": True, "user_text": "", "variables": {"composer": "quarterly numbers"},
        }, "Summarise quarterly numbers."),
        ("edited", {
            **base, "original_content": "Report on {{removed}}.", "edited": True,
            "variables": {"topic": "latency", "removed": "private stale value"},
        }, "Report on latency.\n\nKeep it brief."),
        ("default", {
            **base, "original_content": "Report on {{topic|latency}}.",
            "template_content": "Report on {{topic|latency}}.", "variables": {},
        }, "Report on latency.\n\nKeep it brief."),
        ("prototype-keys", {
            **base, "content": "Compare Alpha with Beta.",
            "original_content": "Compare {{constructor}} with {{__proto__}}.",
            "template_content": "Compare {{constructor}} with {{__proto__}}.",
            "variables": {"constructor": "Alpha", "__proto__": "Beta"},
        }, "Compare Alpha with Beta.\n\nKeep it brief."),
        ("prototype-unfilled", {
            **base, "content": "Compare {{constructor}} with {{__proto__}}.",
            "original_content": "Compare {{constructor}} with {{__proto__}}.",
            "template_content": "Compare {{constructor}} with {{__proto__}}.", "variables": {},
        }, "Compare {{constructor}} with {{__proto__}}.\n\nKeep it brief."),
    ]


def _chat_boundary(path, info, content):
    storage = MemoryContainer()
    events = []
    author = {
        "userId": USER["user_id"], "displayName": USER["display_name"],
        "userPrincipalName": USER["email"], "email": USER["email"],
    }
    namespace = {
        "data": {"prompt_info": deepcopy(info)}, "user_message": content,
        "conversation_id": "conversation-1", "time": time, "random": random,
        "datetime": datetime, "uuid": uuid, "json": json,
        "cosmos_messages_container": storage,
        "build_prompt_selection_metadata": build_prompt_selection_metadata,
        "build_user_message_persisted_stream_event": build_user_message_persisted_stream_event,
        "get_current_user_info": lambda: author,
        "publish_background_event": events.append,
        "debug_print": lambda *args, **kwargs: None,
        "_build_capability_usage_metadata": lambda **kwargs: kwargs,
        "_build_agent_selection_metadata": lambda *args: {"selected_agent": "agent-1"},
        "DOCUMENT_ACTION_TYPE_NONE": "none", "request_document_context_enabled": False,
        "effective_document_scope": "personal", "effective_selected_document_ids": [],
        "effective_selected_document_id": None, "effective_active_group_id": None,
        "effective_active_group_ids": [], "effective_active_public_workspace_ids": [],
        "effective_active_public_workspace_id": None, "request_agent_info": None,
        "assigned_knowledge_filters": None, "gpt_model": "test-deployment",
        "frontend_gpt_model": "test-deployment", "gpt_endpoint_id": None,
        "gpt_model_id": None, "gpt_provider": "azure_openai", "gpt_model_icon": None,
        "gpt_response_length": 1000, "reasoning_effort": None, "search_results": [],
    }
    for flag in (
        "image_gen_enabled", "hybrid_search_enabled", "web_search_enabled",
        "url_access_enabled", "source_review_enabled", "deep_research_enabled",
    ):
        namespace[flag] = False

    if path == "document-action":
        function = _function("route_backend_chats.py", "execute_document_action_chat_request")
        first = next(index for index, statement in enumerate(function.body)
                     if _assigns(statement, "previous_thread_id"))
        body = function.body[first:]
        namespace.update({
            "_get_latest_chat_thread_id": lambda conversation_id: "previous-thread",
            "user_id": USER["user_id"], "normalized_action": {"type": "summarize"},
            "auto_linked_chat_upload_document_ids": [], "make_json_serializable": lambda value: value,
            "_build_document_action_user_metadata": lambda **kwargs: {
                "user_info": {"user_id": USER["user_id"]},
                "thread_info": {
                    "thread_id": kwargs["current_thread_id"],
                    "previous_thread_id": kwargs["previous_thread_id"],
                },
                "workspace_search": {"search_enabled": True},
                "document_action": kwargs["normalized_action"],
            },
        })
    else:
        name = "chat_stream_api" if path == "chat-stream" else "chat_api"
        function = _function("route_backend_chats.py", name)
        candidates = [
            node.orelse for node in ast.walk(function)
            if isinstance(node, ast.If)
            and any(_assigns(statement, "user_message_doc") for statement in node.orelse)
            and any(_is_message_write(statement) for statement in node.orelse)
        ]
        assert len(candidates) == 1, f"Expected one new-user persistence branch in {name}"
        body = candidates[0]
    write = next(index for index, statement in enumerate(body) if _is_message_write(statement))
    document = _execute_boundary(body[:write + 2], namespace, "user_message_doc", events)
    stored = storage.read_item(document["id"], document["conversation_id"])
    assert stored == document
    assert stored["metadata"]["user_info"]["user_id"] == USER["user_id"]
    assert stored["metadata"]["thread_info"]["previous_thread_id"] == "previous-thread"
    assert len(events) == 1
    acknowledgement = json.loads(events[0].removeprefix("data:").strip())
    assert acknowledgement["message_persisted"] is True
    assert acknowledgement["user_message_id"] == stored["id"]
    return stored, deepcopy(stored)


def _orchestration_boundary(info, content):
    storage = MemoryContainer()
    context = load_modules().context
    authorize = Mock()
    namespace = {
        "data": {"prompt_info": deepcopy(info)}, "message": content,
        "resolved_conversation_id": "conversation-1", "turn_id": "turn-1",
        "user_id": USER["user_id"], "previous": None,
        "_authorize_context_conversation": authorize,
        "normalize_history_message": context.normalize_history_message,
        "ConversationContextError": context.ConversationContextError,
        "CosmosResourceNotFoundError": KeyError,
        "build_prompt_selection_metadata": build_prompt_selection_metadata,
        "cosmos_messages_container": storage, "datetime": datetime,
        "timezone": timezone, "uuid": uuid, "logging": logging, "log_event": Mock(),
    }
    _load_functions("route_backend_orchestration.py", namespace, "_now_iso", "_save_message", "_save_turn_message")
    function = _function("route_backend_orchestration.py", "orchestration_plan")
    generator = next(node for node in ast.walk(function)
                     if isinstance(node, ast.FunctionDef) and node.name == "generate")
    body = next(node.body for node in generator.body if isinstance(node, ast.Try))
    first = next(index for index, statement in enumerate(body)
                 if _assigns(statement, "prompt_selection"))
    message_id = _execute_boundary(body[first:first + 2], namespace, "user_message_id", [])
    assert message_id
    stored = storage.read_item(message_id, "conversation-1")
    authorize.assert_called_once_with("conversation-1", USER["user_id"])
    assert stored["metadata"]["orchestration"]["turn_id"] == "turn-1"
    if build_prompt_selection_metadata(info, content):
        assert stored["metadata"]["orchestration_turn_id"] == "turn-1"
    return stored, deepcopy(stored)


def _shared_boundary(path, info, content):
    storage = MemoryContainer()
    conversations = MemoryContainer()
    conversation = {
        "id": "conversation-1", "conversation_kind": "collaborative",
        "chat_type": "personal_multi_user", "created_by_user_id": USER["user_id"],
        "created_by_display_name": USER["display_name"], "participants": [],
    }
    conversations.upsert_item(conversation)
    events = []
    authorized = []
    mention = {"user_id": "colleague-2", "display_name": "Colleague", "email": ""}

    def authorize(user_id, document):
        assert user_id == USER["user_id"]
        assert document["id"] == conversation["id"]
        authorized.append(document["id"])

    namespace = {
        **vars(collaboration_models),
        "deepcopy": deepcopy, "Response": Response, "current_app": current_app,
        "jsonify": jsonify, "request": request, "session": session,
        "stream_with_context": stream_with_context, "logging": logging, "log_event": Mock(),
        "cosmos_collaboration_messages_container": storage,
        "cosmos_collaboration_conversations_container": conversations,
        "CosmosResourceNotFoundError": type("MissingRecord", (Exception,), {}),
        "build_prompt_selection_metadata": build_prompt_selection_metadata,
        "build_user_message_persisted_stream_event": build_user_message_persisted_stream_event,
        "_require_collaboration_feature_enabled": lambda: None,
        "_get_current_collaboration_user": lambda: USER,
        "get_collaboration_conversation": lambda identifier: conversations.read_item(identifier, identifier),
        "assert_user_can_participate_in_collaboration_conversation": authorize,
        "resolve_collaboration_mentions": lambda document, mentions: mentions,
        "ensure_collaboration_source_conversation": lambda document, user: ({"id": "source-1"}, document),
        "create_collaboration_message_notifications": Mock(),
        "serialize_collaboration_conversation": lambda document, **kwargs: deepcopy(document),
        "get_user_state_or_none": lambda *args: None,
        "is_group_collaboration_conversation": lambda document: False,
        "is_personal_collaboration_conversation": lambda document: True,
        "get_collaboration_visibility_mode": lambda document: "explicit_participants",
        "invalidate_conversation_cache_for_item": Mock(), "log_chat_activity": Mock(),
        "COLLABORATION_EVENT_REGISTRY": SimpleNamespace(
            publish=lambda identifier, event: events.append(deepcopy(event)),
        ),
    }
    _load_functions(
        "functions_collaboration.py", namespace, "persist_collaboration_message",
        "_save_collaboration_message_doc", "serialize_collaboration_message",
        "_get_collaboration_display_role",
    )
    route_name = "stream_collaboration_message_api" if path == "shared-stream" else "post_collaboration_message_api"
    _load_functions(
        "route_backend_collaboration.py", namespace, route_name,
        "_build_collaboration_event", "_build_collaboration_stream_request_payload",
    )
    data = {
        "content": content, "prompt_info": deepcopy(info), "reply_to_message_id": "earlier-message",
        "mentioned_participants": [mention], "invocation_target": {"type": "model", "id": "model-1"},
    }
    app = Flask(__name__)
    with app.test_request_context("/", method="POST", json=data):
        response = app.make_response(namespace[route_name](conversation["id"]))
        assert response.status_code == (200 if path == "shared-stream" else 201), (
            response.get_data(as_text=True), namespace["log_event"].call_args_list,
        )
        if path == "shared-stream":
            acknowledgement = json.loads(next(iter(response.response)).removeprefix("data:").strip())
            assert acknowledgement["message_persisted"] is True
            response.close()
        else:
            echo = response.get_json()["message"]

    assert authorized == [conversation["id"]]
    assert len(storage.rows) == 1
    stored = next(iter(storage.rows.values()))
    assert len(events) == 1
    event_message = events[0]["payload"]["message"]
    assert event_message["metadata"] == stored["metadata"]
    assert stored["metadata"]["sender"] == USER
    assert stored["metadata"]["user_info"]["user_id"] == USER["user_id"]
    assert stored["metadata"]["mentioned_user_ids"] == [mention["user_id"]]
    assert stored["reply_to_message_id"] == "earlier-message"
    if path == "shared-stream":
        assert stored["metadata"]["ai_invocation_target"] == data["invocation_target"]
        assert stored["metadata"]["source_conversation_id"] == "source-1"
        assert acknowledgement["user_message_id"] == stored["id"]
        source_request = namespace["_build_collaboration_stream_request_payload"](data, "source-1", content)
        assert source_request["prompt_info"] == info
        assert source_request["message"] == content
        echo = event_message
    else:
        assert echo == event_message
    return deepcopy(stored), echo


def exercise_persistence(path, info, content):
    if path == "orchestration":
        return _orchestration_boundary(info, content)
    if path.startswith("shared-"):
        return _shared_boundary(path, info, content)
    return _chat_boundary(path, info, content)


def build_prompt_lifecycle_fixtures():
    """Feed real backend writes/echoes to the TypeScript snapshot recovery checks over stdin."""
    fixtures = []
    for path in SEND_PATHS:
        for case, info, content in prompt_cases():
            stored, echo = exercise_persistence(path, info, content)
            fixtures.append({
                "path": path, "case": case, "promptInfo": info, "stored": stored, "echo": echo,
            })
    return fixtures


@pytest.mark.parametrize("path", SEND_PATHS)
@pytest.mark.parametrize("case,info,content", prompt_cases(), ids=lambda value: value if isinstance(value, str) else None)
def test_prompt_snapshot_survives_storage_and_echo(path, case, info, content):
    stored, echo = exercise_persistence(path, info, content)
    expected = build_prompt_selection_metadata(info, content)
    assert expected is not None
    assert stored["content"] == content
    assert stored["metadata"]["prompt_selection"] == expected
    assert echo["metadata"]["prompt_selection"] == expected
    assert json.loads(json.dumps(stored))["metadata"]["prompt_selection"] == expected
    assert "removed" not in expected["prompt_variables"]


@pytest.mark.parametrize("path", SEND_PATHS)
@pytest.mark.parametrize("info", [None, {}, [], "invalid", {"content": "Different prompt."}])
def test_absent_or_unusable_metadata_does_not_change_messages(path, info):
    stored, echo = exercise_persistence(path, info, "Only the user's text.")
    assert stored["content"] == "Only the user's text."
    assert "prompt_selection" not in stored.get("metadata", {})
    assert "prompt_selection" not in echo.get("metadata", {})
    if path == "orchestration":
        assert stored["metadata"] == {"orchestration": {"turn_id": "turn-1"}}
        assert echo["metadata"] == stored["metadata"]


def test_legacy_metadata_requires_a_complete_prompt_or_exact_delimiter():
    info = {"index": 2, "id": "old", "name": "Old prompt", "content": "Instructions."}
    for content in ("Instructions.", "Instructions.\n\nQuestion."):
        metadata = build_prompt_selection_metadata(info, content)
        assert metadata["selected_prompt_index"] == 2
        assert metadata["user_text"] is None
        assert "composer_text" not in metadata
    for content in ("Instructions.Changed", "Instructions.\nQuestion.", "Question.\n\nInstructions."):
        assert build_prompt_selection_metadata(info, content) is None


@pytest.mark.parametrize("change", [
    {"composer_text": ["not text"]}, {"composer_embedded": "false"},
    {"template_content": None}, {"user_text": {"bad": True}},
    {"user_text": "Old question."}, {"composer_text": "Old question."},
    {"composer_embedded": True},
])
def test_malformed_or_mismatched_snapshots_are_not_persisted(change):
    _, info, content = prompt_cases()[0]
    assert build_prompt_selection_metadata({**info, **change}, content) is None


def test_changed_or_masked_content_does_not_validate_against_a_stale_snapshot():
    _, info, content = prompt_cases()[0]
    assert build_prompt_selection_metadata(info, content.replace("Keep it brief.", "Different question.")) is None
    assert build_prompt_selection_metadata(info, content.replace("latency", "[hidden]")) is None
    _, embedded, embedded_content = prompt_cases()[2]
    assert build_prompt_selection_metadata({**embedded, "composer_text": "private other text"}, embedded_content) is None


def test_only_active_string_variables_are_recorded():
    template = "Use {{Customer-name|Guest}} and {{constructor}}. `{{inline}}` \\{{escaped}}\n```\n{{code}}\n```"
    info = {
        "content": template, "template_content": template, "composer_text": "",
        "composer_embedded": False, "user_text": "",
        "variables": {
            "customer_name": "Ada", "constructor": "Allowed name", "inline": "no",
            "escaped": "no", "code": "no", "removed": "no", "wrong_type": ["no"],
        },
        "id": {"bad": "type"}, "name": ["bad"], "edited": "false", "index": True,
    }
    metadata = build_prompt_selection_metadata(info, template)
    assert metadata["prompt_variables"] == {"customer_name": "Ada", "constructor": "Allowed name"}
    assert metadata["prompt_id"] is None
    assert metadata["prompt_name"] is None
    assert metadata["selected_prompt_index"] is None
    assert metadata["prompt_edited"] is False


def test_version_includes_the_persistence_fix():
    assert_app_version_at_least("0.261.096")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
