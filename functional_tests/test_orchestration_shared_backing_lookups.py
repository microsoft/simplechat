# test_orchestration_shared_backing_lookups.py
#!/usr/bin/env python3
"""
Functional test for lookups by a shared conversation's id while Orchestrate's backing exists.
Version: 0.261.270
Implemented in: 0.261.270

Orchestrate keeps a shared conversation's plans in a hidden personal record stored under the
shared conversation's own id (microsoft/simplechat#1659). Code that looks a conversation id up
in personal storage first must treat that record as part of the shared conversation. Otherwise
reloading the conversation reopens it as a personal chat for the person who started it, other
participants are refused images, summaries and exports, uploads land in the wrong place, and
Microsoft 365 action cards disappear.

These tests run the real lookups over in-memory storage, with the backing record present.
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest
from flask import Blueprint, Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response

TESTS = Path(__file__).resolve().parent
APP = TESTS.parent / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(TESTS))

from test_orchestration_harness_routes import login, modules, real_http_harness  # noqa: E402,F401
from test_orchestration_shared_conversations import SHARED_ID, shared  # noqa: E402,F401
from test_support.versioning import assert_app_version_at_least  # noqa: E402

CLASSIC_SOURCE_ID = "classic-source-1"


def accepted(conversation):
    return {
        participant["user_id"] for participant in conversation.get("participants") or []
        if participant.get("status") == "accepted"
    }


def view(user_id, conversation, allow_pending=False):
    if user_id not in accepted(conversation):
        raise PermissionError("You are not a participant in this collaborative conversation")
    return {"user_state": None, "membership_status": "accepted"}


@pytest.fixture
def backed(shared):
    """The shared conversation with its Orchestrate backing and a classic source conversation."""
    collaboration = shared.shared.read_item(SHARED_ID, SHARED_ID)
    collaboration["source_conversation_id"] = CLASSIC_SOURCE_ID
    shared.shared.upsert_item(collaboration)
    shared.harness.conversations.create_item({
        "id": SHARED_ID, "user_id": "owner", "title": "Launch plan",
        "conversation_kind": "collaboration_source", "collaboration_conversation_id": SHARED_ID,
        "is_hidden": True, "context": [], "chat_type": "personal_single_user",
    })
    return shared


@pytest.fixture
def conversation_routes(backed, monkeypatch):
    routes = importlib.import_module("route_backend_conversations")
    monkeypatch.setattr(routes, "cosmos_conversations_container", backed.harness.conversations)
    monkeypatch.setattr(routes, "get_settings", lambda: {"enable_collaborative_conversations": True})
    monkeypatch.setattr(routes, "assert_user_can_view_collaboration_conversation", view)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="shared-backing-lookups")
    blueprint = Blueprint("backend_conversations", __name__)
    routes.register_route_backend_conversations(blueprint)
    app.register_blueprint(blueprint)
    backed.routes = routes
    backed.conversations_app = app
    backed.conversations_client = Client(app, Response)
    return backed


def kind(runtime, user_id, conversation_id=SHARED_ID):
    runtime.app, runtime.client = runtime.conversations_app, runtime.conversations_client
    login(runtime, user_id=user_id)
    response = runtime.client.get(f"/api/conversations/{conversation_id}/kind")
    return response.status_code, response.get_json()


def test_version_includes_shared_backing_lookups():
    assert_app_version_at_least("0.261.270")


def test_reopening_a_shared_conversation_never_turns_it_into_a_personal_chat(conversation_routes):
    for user_id in ("owner", "guest"):
        status, body = kind(conversation_routes, user_id)
        assert status == 200 and body["kind"] == "collaborative", (user_id, body)
        assert body["conversation"]["id"] == SHARED_ID
    status, _body = kind(conversation_routes, "stranger")
    assert status == 404


def test_an_earlier_private_copy_opens_as_the_shared_conversation(conversation_routes):
    conversations = conversation_routes.harness.conversations
    conversations.upsert_item({"id": SHARED_ID, "user_id": "guest", "title": "New Conversation", "chat_type": "new"})

    status, body = kind(conversation_routes, "guest")
    assert status == 200 and body["kind"] == "collaborative"
    # Someone who can no longer see the shared conversation still reaches their own copy.
    collaboration = conversation_routes.shared.read_item(SHARED_ID, SHARED_ID)
    collaboration["participants"] = [p for p in collaboration["participants"] if p["user_id"] != "guest"]
    conversation_routes.shared.upsert_item(collaboration)
    status, body = kind(conversation_routes, "guest")
    assert status == 200 and body["kind"] == "personal"


def test_personal_conversations_are_unchanged(conversation_routes):
    conversation_routes.harness.conversations.create_item({"id": "personal-1", "user_id": "owner", "title": "Mine"})
    owner_result = kind(conversation_routes, "owner", "personal-1")
    guest_status, _guest_body = kind(conversation_routes, "guest", "personal-1")
    assert owner_result == (200, {"conversation_id": "personal-1", "kind": "personal"})
    assert guest_status == 404


def test_personal_routes_treat_the_backing_as_part_of_the_shared_conversation(conversation_routes):
    routes = conversation_routes.routes
    with pytest.raises(LookupError):
        routes._authorize_personal_conversation_read("owner", SHARED_ID)
    # Images fall through to the shared conversation, so every participant can see them.
    for user_id in ("owner", "guest"):
        conversation, kind_name = routes._authorize_image_conversation_read(user_id, SHARED_ID)
        assert kind_name == "collaboration" and conversation["id"] == SHARED_ID
    with pytest.raises(PermissionError):
        routes._authorize_image_conversation_read("stranger", SHARED_ID)
    monkeypatched = routes.assert_user_can_participate_in_collaboration_conversation
    try:
        routes.assert_user_can_participate_in_collaboration_conversation = view
        item, scope_kind = routes._load_scope_lock_conversation(SHARED_ID, "guest")
    finally:
        routes.assert_user_can_participate_in_collaboration_conversation = monkeypatched
    assert scope_kind == "collaboration" and item["id"] == SHARED_ID


def test_metadata_exports_and_tools_use_the_shared_conversation(backed, monkeypatch):
    metadata = importlib.import_module("functions_conversation_metadata")
    monkeypatch.setattr(metadata, "cosmos_conversations_container", backed.harness.conversations)
    item, source = metadata._get_conversation_item_with_source(SHARED_ID)
    assert source == "collaboration" and item["id"] == SHARED_ID

    export = importlib.import_module("route_backend_conversation_export")
    monkeypatch.setattr(export, "cosmos_conversations_container", backed.harness.conversations)
    monkeypatch.setattr(export, "assert_user_can_view_collaboration_conversation", view)
    for user_id in ("owner", "guest"):
        loaded = export._load_exportable_conversation_for_user(user_id, SHARED_ID)
        assert loaded is not None and loaded[0]["id"] == SHARED_ID, user_id

    tools = importlib.import_module("functions_mcp_server_tools")
    monkeypatch.setattr(tools, "cosmos_conversations_container", backed.harness.conversations)
    monkeypatch.setattr(tools, "assert_user_can_view_collaboration_conversation", view)
    item, source = tools._authorize_personal_conversation_read("owner", SHARED_ID)
    assert source == "collaboration" and item["id"] == SHARED_ID


def test_chat_never_writes_into_the_backing_directly(backed, monkeypatch):
    chats = importlib.import_module("route_backend_chats")
    monkeypatch.setattr(chats, "cosmos_conversations_container", backed.harness.conversations)
    for user_id in ("owner", "guest"):
        with pytest.raises(LookupError):
            chats._resolve_authorized_conversation_context(user_id, SHARED_ID)


def test_uploads_go_to_the_shared_conversation_not_the_backing(backed, monkeypatch):
    chats = importlib.import_module("route_frontend_chats")
    monkeypatch.setattr(chats, "cosmos_conversations_container", backed.harness.conversations)
    monkeypatch.setattr(chats, "assert_user_can_participate_in_collaboration_conversation", view)
    sources = []

    def ensure_source(collaboration, current_user):
        sources.append(current_user)
        return {"id": CLASSIC_SOURCE_ID, "user_id": "owner"}, collaboration

    monkeypatch.setattr(chats, "ensure_collaboration_source_conversation", ensure_source)
    context = chats._resolve_chat_upload_context(SHARED_ID, "guest", {"userId": "guest"})
    assert context["conversation_id"] == CLASSIC_SOURCE_ID
    assert context["response_conversation_id"] == SHARED_ID and len(sources) == 1


def test_microsoft_365_cards_keep_resolving_to_the_classic_source(backed, monkeypatch):
    runtime = importlib.import_module("functions_m365_runtime")
    monkeypatch.setattr(runtime, "cosmos_conversations_container", backed.harness.conversations)
    monkeypatch.setattr(runtime, "assert_user_can_participate_in_collaboration_conversation", view)
    for user_id in ("owner", "guest"):
        resolved_conversation_id = runtime.resolve_m365_audit_conversation_id(user_id, SHARED_ID)
        assert resolved_conversation_id == CLASSIC_SOURCE_ID
    backed.harness.conversations.create_item({"id": "personal-2", "user_id": "owner"})
    resolved_personal_id = runtime.resolve_m365_audit_conversation_id("owner", "personal-2")
    assert resolved_personal_id == "personal-2"


def _function_source(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(path.read_text(encoding="utf-8"), node)
    raise AssertionError(f"{name} is not defined in {path.name}")


@pytest.mark.parametrize(("module", "function"), [
    ("route_backend_conversations.py", "generate_conversation_summary_api"),
    ("functions_simplechat_operations.py", "add_conversation_message_for_current_user"),
    ("route_frontend_conversations.py", "get_agent_citation_artifact"),
])
def test_other_personal_first_lookups_recognize_the_backing(module, function):
    source = _function_source(APP / module, function)
    assert "is_shared_conversation_backing(" in source or "_authorize_personal_conversation_read(" in source


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
