# chat_stop_runtime.py
"""Real Flask chat/attempt/history owners with isolated SDK-shaped storage I/O.

Version: 0.261.430
Implemented in: 0.261.430
Shared by route regressions and persisted-payload browser reload tests.
"""

import importlib
import asyncio
import re
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from threading import Event, Thread

from flask import Blueprint, Flask
import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from test_support.offline_bootstrap import offline_app_imports
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_chat_soft_deleted_message_visibility_fix import FakeContainer as QueryInterpreter


ROOT = Path(__file__).resolve().parents[2]


class StopMessageContainer(AtomicMemoryContainer):
    """SDK-default message I/O with a barrier after an observed missing read."""

    def __init__(self, partition_field="conversation_id"):
        super().__init__(partition_field)
        self.after_missing_read = None

    def read_item(self, item, partition_key, **kwargs):
        try:
            return super().read_item(item, partition_key, **kwargs)
        except CosmosResourceNotFoundError:
            callback = self.after_missing_read
            if callback:
                self.after_missing_read = None
                callback(item, partition_key)
            raise

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        # Apply TOP only after the reused interpreter's role/thread predicates.
        unbounded = re.sub(r"SELECT TOP \d+\s+", "SELECT ", query)
        rows = super().query_items(unbounded, parameters, partition_key, **kwargs)
        self.queries[-1] = (query, deepcopy(parameters), partition_key)
        values = {item["name"]: item["value"] for item in parameters or []}
        if "@source_message_id" in values:
            rows = [row for row in rows
                    if (row.get("metadata") or {}).get("source_message_id") == values["@source_message_id"]]
        if "SELECT VALUE COUNT(1)" in query:
            if "c.is_hidden = true" in query:
                rows = [row for row in rows if row.get("is_hidden") is True
                        and row.get("collaboration_conversation_id") != row.get("id")]
            return [len(rows)]
        if "@notification_type" in query:
            wanted = next(item["value"] for item in parameters if item["name"] == "@notification_type")
            return [{
                "conversation_id": row["metadata"]["conversation_id"],
                "message_id": row["metadata"].get("message_id"),
                "created_at": row.get("created_at"),
            } for row in rows if row.get("notification_type") == wanted]
        interpreter = QueryInterpreter()
        interpreter.items = {row["id"]: deepcopy(row) for row in rows}
        interpreted_query = re.sub(
            r"TOP (@\w+)", lambda match: f"TOP {int(values[match[1]])}", query,
        )
        # The reused interpreter implements message query syntax; the SDK base
        # already enforced this container's own partition, including /id stores.
        return interpreter.query_items(interpreted_query, parameters, None, **kwargs)

    def delete_item(self, item, partition_key, **kwargs):
        if kwargs.get("etag") is not None:
            return super().delete_item(item, partition_key, **kwargs)
        # The installed SDK also allows an explicitly unconditional delete.
        with self._lock:
            self.read_item(item, partition_key)
            del self.items[(partition_key, item)]

    def replace_item(self, item, body, **kwargs):
        if kwargs.get("etag") is not None or kwargs.get("match_condition") is not None:
            return super().replace_item(item, body, **kwargs)
        with self._lock:
            self.read_item(item, body[self.partition_field])
            if item != body["id"]:
                raise ValueError("Replacement changed identity")
            return self._save(body)


@pytest.fixture(scope="module")
def stop_modules():
    # Playwright owns the test thread's running event loop. Bootstrap/teardown's
    # isolated asyncio loop belongs to this dedicated I/O-fixture thread instead.
    ready, finished = Event(), Event()
    result, failures = [], []

    def load():
        try:
            with offline_app_imports() as bootstrap:
                asyncio.set_event_loop(bootstrap.loop)
                original_path = list(sys.path)
                sys.path.insert(0, str(ROOT / "application" / "single_app"))
                try:
                    result.append(SimpleNamespace(
                        retry=importlib.import_module("functions_chat_retry"),
                        chats=importlib.import_module("route_backend_chats"),
                        history=importlib.import_module("route_backend_conversations"),
                        history_authorize=importlib.import_module(
                            "route_backend_conversations"
                        )._authorize_personal_conversation_read,
                        collaboration=importlib.import_module("route_backend_collaboration"),
                        collaboration_owner=importlib.import_module("functions_collaboration"),
                    ))
                    ready.set()
                    finished.wait()
                finally:
                    sys.path[:] = original_path
        except BaseException as error:
            failures.append(error)
            ready.set()

    thread = Thread(target=load, daemon=True)
    thread.start()
    try:
        if not ready.wait(120):
            raise AssertionError("Offline chat fixture did not initialize.")
        if failures:
            raise failures[0]
        yield result[0]
    finally:
        finished.set()
        thread.join(timeout=30)
        if thread.is_alive():
            raise AssertionError("Offline chat fixture did not stop.")
        if failures:
            raise failures[0]


@pytest.fixture
def stop_world(stop_modules, monkeypatch):
    controls = AtomicMemoryContainer("destination_conversation_id")
    messages = StopMessageContainer()
    conversations = StopMessageContainer("id")
    conversations.create_item({"id": "chat", "user_id": "owner"})

    def authorize(actor="owner", destination="chat"):
        conversation = conversations.read_item(destination, destination)
        if conversation["user_id"] != actor:
            raise PermissionError()
        return conversation

    chats = stop_modules.chats
    for name in ("login_required", "user_required"):
        monkeypatch.setattr(chats, name, lambda view: view)
    monkeypatch.setattr(chats, "get_current_user_id", lambda: "owner")
    monkeypatch.setattr(chats, "_authorize_personal_conversation_access", authorize)
    monkeypatch.setattr(chats, "cosmos_conversation_handoffs_container", controls)
    monkeypatch.setattr(chats, "cosmos_messages_container", messages)
    monkeypatch.setattr(chats, "cosmos_conversations_container", conversations)
    monkeypatch.setattr(chats, "log_event", lambda *args, **kwargs: None)
    cache_meta, cache_events = {}, {}
    monkeypatch.setattr(chats.app_settings_cache, "get_stream_session_meta", lambda key: deepcopy(cache_meta.get(key)))
    monkeypatch.setattr(chats.app_settings_cache, "set_stream_session_meta",
                        lambda key, value, **kwargs: cache_meta.__setitem__(key, deepcopy(value)))
    monkeypatch.setattr(chats.app_settings_cache, "initialize_stream_session_cache",
                        lambda key, value, **kwargs: (cache_meta.__setitem__(key, deepcopy(value)), cache_events.__setitem__(key, [])))
    monkeypatch.setattr(chats.app_settings_cache, "append_stream_session_event",
                        lambda key, value, **kwargs: cache_events.setdefault(key, []).append(value))
    monkeypatch.setattr(chats.app_settings_cache, "get_stream_session_events",
                        lambda key, start_index=0: cache_events.get(key, [])[start_index:])
    monkeypatch.setattr(chats, "CHAT_STREAM_REGISTRY", chats.ActiveConversationStreamRegistry())
    app = Flask("durable-stop")
    app.config["TESTING"] = True
    app.secret_key = "test-only"
    bp = Blueprint("stop", __name__)
    chats.register_route_backend_chats(bp)
    app.register_blueprint(bp)
    history = stop_modules.history
    for name in ("login_required", "user_required"):
        monkeypatch.setattr(history, name, lambda view: view)
    monkeypatch.setattr(history, "get_current_user_id", lambda: "owner")
    monkeypatch.setattr(history, "_authorize_personal_conversation_read", authorize)
    monkeypatch.setattr(history, "get_settings", lambda *args, **kwargs: {})
    monkeypatch.setattr(history, "cosmos_conversation_handoffs_container", controls)
    monkeypatch.setattr(history, "cosmos_messages_container", messages)
    monkeypatch.setattr(history, "cosmos_conversations_container", conversations)
    monkeypatch.setattr(history, "hydrate_m365_pending_action_cards", lambda rows, *args: rows)
    monkeypatch.setattr(history, "log_event", lambda *args, **kwargs: None)
    history_bp = Blueprint("stop_history", __name__)
    history.register_route_backend_conversations(history_bp)
    app.register_blueprint(history_bp)
    collaboration = stop_modules.collaboration
    shared = AtomicMemoryContainer("id")
    shared_messages = StopMessageContainer()
    members = AtomicMemoryContainer("user_id")
    shared.create_item({
        "id": "shared", "conversation_kind": "collaborative", "chat_type": "personal_multi_user",
        "created_by_user_id": "owner",
    })
    for member in ("owner", "collaborator"):
        members.create_item({
            "id": f"{member}:shared", "user_id": member, "conversation_id": "shared",
            "membership_status": "accepted",
        })
    monkeypatch.setattr(stop_modules.collaboration_owner, "cosmos_collaboration_conversations_container", shared)
    monkeypatch.setattr(stop_modules.collaboration_owner, "cosmos_collaboration_user_state_container", members)
    monkeypatch.setattr(stop_modules.collaboration_owner, "cosmos_collaboration_messages_container", shared_messages)
    monkeypatch.setattr(stop_modules.collaboration_owner, "cosmos_conversations_container", conversations)
    monkeypatch.setattr(stop_modules.collaboration_owner, "cosmos_messages_container", messages)
    actor = {"value": "owner"}
    for name in ("login_required", "user_required"):
        monkeypatch.setattr(collaboration, name, lambda view: view)
    monkeypatch.setattr(collaboration, "_get_current_collaboration_user", lambda: {"user_id": actor["value"]})
    monkeypatch.setattr(collaboration, "_require_collaboration_feature_enabled", lambda: None)
    monkeypatch.setattr(collaboration, "cosmos_conversation_handoffs_container", controls)
    monkeypatch.setattr(collaboration, "cosmos_messages_container", messages)
    monkeypatch.setattr(collaboration, "cosmos_collaboration_messages_container", shared_messages)
    monkeypatch.setattr(collaboration, "cosmos_conversations_container", conversations)
    monkeypatch.setattr(collaboration, "log_event", lambda *args, **kwargs: None)
    for name in ("refresh_azure_maps_message_citations", "sanitize_saved_analysis_messages",
                 "hydrate_m365_pending_action_cards", "public_history_messages"):
        monkeypatch.setattr(collaboration, name, lambda rows, *args, **kwargs: rows)
    monkeypatch.setattr(collaboration, "attach_generated_file_approval_state", lambda *args: None)
    shared_bp = Blueprint("stop_collaboration", __name__)
    collaboration.register_route_backend_collaboration(shared_bp)
    app.register_blueprint(shared_bp)

    def store(submission="submission-a", actor="owner", destination="chat", clock=lambda: 1000):
        return stop_modules.retry.ChatAttemptStore(
            controls, messages, actor_id=actor, conversation_id=destination,
            submission_id=submission, authorize=lambda: authorize(actor, destination), clock=clock,
        )

    question = {
        "id": "question-a", "conversation_id": "chat", "role": "user",
        "content": "Question A", "timestamp": "2026-11-16T20:00:00Z",
        "metadata": {"thread_info": {"thread_id": "thread-a", "thread_attempt": 1, "active_thread": True}},
    }
    reply = {
        "id": "reply-a", "conversation_id": "chat", "role": "assistant",
        "content": "Safe partial answer", "timestamp": "2026-11-16T20:00:01Z",
        "metadata": {"thread_info": deepcopy(question["metadata"]["thread_info"])},
    }
    return SimpleNamespace(
        **vars(stop_modules), controls=controls, messages=messages,
        conversations=conversations, authorize=authorize, app=app,
        store=store, question=question, reply=reply,
        shared=shared, shared_messages=shared_messages, members=members, actor=actor,
    )
