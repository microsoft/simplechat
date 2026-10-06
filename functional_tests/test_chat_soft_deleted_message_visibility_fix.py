#!/usr/bin/env python3
# test_chat_soft_deleted_message_visibility_fix.py
"""
Functional test for deleted chat messages that came back as masked messages.
Version: 0.261.253
Implemented in: 0.261.253

With conversation archiving enabled, deleting a chat message keeps its document with
``metadata.is_deleted`` set, and masks it only as a fail-safe. This test ensures such a
message stays deleted everywhere: the message list, attempt switching and promotion, retry
and edit, both mask routes, forks, shared-conversation copies, search, MCP reads, the
conversation summary, and every history path that reaches the model. It also checks that
deleting only an answer no longer re-activates an older attempt, and that the V2 client
filters deleted messages and counts attempts by position. Refs #1649.

The probe runs in a fresh process with the real application modules, network access
blocked (``test_support.offline_bootstrap``), and in-memory Cosmos containers. Every
scenario runs and reports on its own, and the checks are explicit, so they also run under
optimized Python.
"""

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
V2_SRC = ROOT / "application" / "v2_ui" / "src"
PROBE_FLAG = "--probe"
PROBE_OK = "SOFT_DELETE_PROBE_OK"
PROBE_FAILED = "SOFT_DELETE_PROBE_FAILURES"

USER = "user-owner"
CONVERSATION = "conversation-1"
SHARED_CONVERSATION = "shared-1"
NOT_SOFT_DELETED = "(NOT IS_DEFINED(c.metadata.is_deleted) OR c.metadata.is_deleted != true)"


def check(condition, message):
    """Raise rather than assert, so the check survives python -O."""
    if not condition:
        raise AssertionError(message)


# --------------------------------------------------------------------------------------
# In-memory Cosmos container used by the probe
# --------------------------------------------------------------------------------------

def _path_value(document, path):
    value = document
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


class FakeContainer:
    """Evaluates the small set of query shapes the code under test issues."""

    def __init__(self, items=()):
        self.items = {}
        self.queries = []
        self.revision = 0
        self.reset(items)

    def reset(self, items=()):
        self.items = {}
        self.queries = []
        for item in items:
            self._store(item)

    def _store(self, item):
        self.revision += 1
        saved = copy.deepcopy(item)
        saved["_etag"] = str(self.revision)
        self.items[saved["id"]] = saved
        return copy.deepcopy(saved)

    def get(self, item_id):
        return copy.deepcopy(self.items.get(item_id))

    def read_item(self, item=None, partition_key=None, **kwargs):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        document = self.items.get(item)
        if document is None:
            raise CosmosResourceNotFoundError(status_code=404, message="Not found")
        return copy.deepcopy(document)

    def upsert_item(self, body, **kwargs):
        return self._store(body)

    create_item = upsert_item

    def replace_item(self, item=None, body=None, etag=None, match_condition=None, **kwargs):
        from azure.cosmos.exceptions import CosmosAccessConditionFailedError

        item_id = item if isinstance(item, str) else (item or body)["id"]
        current = self.items.get(item_id)
        if etag is not None and current is not None and current.get("_etag") != etag:
            raise CosmosAccessConditionFailedError(status_code=412, message="Changed")
        return self._store(body)

    def delete_item(self, item=None, partition_key=None, **kwargs):
        item_id = item if isinstance(item, str) else item["id"]
        self.items.pop(item_id, None)

    def query_items(self, query=None, parameters=None, partition_key=None, **kwargs):
        self.queries.append(query)
        params = {entry["name"]: entry["value"] for entry in parameters or []}
        documents = [copy.deepcopy(document) for document in self.items.values()]
        if partition_key is not None:
            documents = [document for document in documents if document.get("conversation_id") == partition_key]

        def equals(field):
            match = re.search(rf"c\.{re.escape(field)}\s*=\s*(?:'([^']*)'|(@\w+))", query)
            if not match:
                return None
            return match.group(1) if match.group(1) is not None else params.get(match.group(2))

        for field in (
            "conversation_id",
            "id",
            "role",
            "parent_message_id",
            "metadata.thread_info.thread_id",
            "metadata.thread_info.previous_thread_id",
        ):
            expected = equals(field)
            if expected is not None:
                documents = [document for document in documents if _path_value(document, field) == expected]

        before = re.search(r"c\.timestamp\s*<\s*(@\w+)", query)
        if before:
            limit = params.get(before.group(1))
            documents = [document for document in documents if str(document.get("timestamp") or "") < limit]
        if NOT_SOFT_DELETED in query:
            documents = [document for document in documents if _path_value(document, "metadata.is_deleted") is not True]

        if "ORDER BY c.metadata.thread_info.thread_attempt" in query:
            documents.sort(key=lambda document: _path_value(document, "metadata.thread_info.thread_attempt") or 0)
        elif "ORDER BY c.timestamp DESC" in query:
            documents.sort(key=lambda document: str(document.get("timestamp") or ""), reverse=True)
        else:
            documents.sort(key=lambda document: str(document.get("timestamp") or ""))

        selected = re.search(r"SELECT\s+(?:TOP\s+(\d+)\s+)?(.+?)\s+FROM\s+c\b", query, re.DOTALL)
        top, fields = (selected.group(1), selected.group(2).strip()) if selected else (None, "*")
        if fields.startswith("VALUE MAX("):
            path = re.search(r"MAX\(c\.([\w.]+)\)", fields).group(1)
            values = [_path_value(document, path) for document in documents]
            values = [value for value in values if value is not None]
            return [max(values) if values else None]
        if top:
            documents = documents[: int(top)]
        if fields == "*":
            return documents

        projected = []
        for document in documents:
            row = {}
            for field in fields.split(","):
                expression, _, alias = field.strip().partition(" as ")
                path = expression.strip()[len("c."):]
                row[alias.strip() or path.split(".")[-1]] = _path_value(document, path)
            projected.append(row)
        return projected


def soft_deleted(document, timestamp="2026-01-01T09:00:00"):
    """Mark a message the way the delete route does when archiving is enabled."""
    document = copy.deepcopy(document)
    document["metadata"].update({
        "is_deleted": True,
        "deleted_by_user_id": USER,
        "deleted_timestamp": timestamp,
        "masked": True,
        "masked_by_user_id": USER,
        "masked_timestamp": timestamp,
    })
    return document


def message(message_id, role, content, timestamp, thread=None, attempt=1, active=True, conversation=CONVERSATION):
    metadata = {}
    if thread:
        metadata["thread_info"] = {
            "thread_id": thread,
            "thread_attempt": attempt,
            "active_thread": active,
            "previous_thread_id": None,
        }
    if role == "user":
        metadata["user_info"] = {"user_id": USER, "display_name": "Owner"}
    return {
        "id": message_id,
        "conversation_id": conversation,
        "role": role,
        "content": content,
        "timestamp": timestamp,
        "metadata": metadata,
    }


def retried_turn(deleted_first_question=False):
    """One turn answered twice: attempt 1 inactive, attempt 2 active."""
    first_question = message("q1", "user", "First wording", "2026-01-01T00:00:01", "t1", 1, False)
    if deleted_first_question:
        first_question = soft_deleted(first_question)
    return [
        first_question,
        message("a1", "assistant", "First answer", "2026-01-01T00:00:02", "t1", 1, False),
        message("q2", "user", "Second wording", "2026-01-01T00:00:03", "t1", 2, True),
        message("a2", "assistant", "Second answer", "2026-01-01T00:00:04", "t1", 2, True),
    ]


def active_flags(store):
    return {
        item_id: _path_value(document, "metadata.thread_info.active_thread")
        for item_id, document in store.items.items()
    }


# --------------------------------------------------------------------------------------
# Probe: runs in a fresh process
# --------------------------------------------------------------------------------------

def run_probe():
    sys.path.insert(0, str(ROOT / "functional_tests"))
    sys.path.insert(0, str(APP_ROOT))

    from contextlib import ExitStack
    from unittest.mock import patch

    from flask import Flask

    from test_support.offline_bootstrap import offline_app_imports

    failures = []

    with offline_app_imports(), ExitStack() as stack:
        import functions_collaboration as collaboration_functions
        import functions_mcp_server_tools as mcp_tools
        import functions_orchestration_context as orchestration_context
        import functions_simplechat_operations as operations
        import route_backend_chats as chats
        import route_backend_collaboration as collaboration_routes
        import route_backend_conversation_export as conversation_export
        import route_backend_conversations as conversations
        from functions_chat_content_checks import ChatContentDecision
        from functions_message_deletion import (
            NOT_SOFT_DELETED_COSMOS_FILTER,
            exclude_soft_deleted_messages,
            is_soft_deleted_message,
            strip_soft_delete_metadata,
        )

        check(NOT_SOFT_DELETED_COSMOS_FILTER == NOT_SOFT_DELETED, "The probe's predicate is out of date")

        messages = FakeContainer()
        shared_messages = FakeContainer()
        conversation_store = FakeContainer([{"id": CONVERSATION, "user_id": USER, "title": "Review"}])
        archive = FakeContainer()
        settings = {"enable_conversation_archiving": True}
        not_required = ChatContentDecision("chat_input", "not_required", "allow", {})
        owner = {"user_id": USER, "display_name": "Owner", "email": "owner@example.test"}
        ghost = soft_deleted(message(
            "ghost", "user", "Deleted before sharing", "2026-01-01T00:00:05", conversation=SHARED_CONVERSATION,
        ))

        for module in (conversations, chats, collaboration_routes):
            for decorator in ("login_required", "user_required"):
                stack.enter_context(patch.object(module, decorator, lambda function: function))
        for module, replacements in (
            (conversations, {
                "get_current_user_id": lambda: USER,
                "get_settings": lambda *args, **kwargs: settings,
                "cosmos_messages_container": messages,
                "cosmos_conversations_container": conversation_store,
                "cosmos_archived_messages_container": archive,
                "cleanup_chat_analysis_messages": lambda *args, **kwargs: None,
                "_rebuild_authorized_personal_conversation_used_documents": lambda *args, **kwargs: None,
                "_invalidate_conversation_cache_after_message_mutation": lambda *args, **kwargs: None,
                "check_chat_content": lambda *args, **kwargs: not_required,
                "debug_print": lambda *args, **kwargs: None,
            }),
            (chats, {
                "get_current_user_id": lambda: USER,
                "get_current_user_info": lambda: {"displayName": "Owner"},
                "cosmos_messages_container": messages,
                "cosmos_conversations_container": conversation_store,
                "persist_chat_reply": lambda container, document, *args, **kwargs: container.upsert_item(document),
            }),
            (collaboration_routes, {
                "_require_collaboration_feature_enabled": lambda: {},
                "_get_current_collaboration_user": lambda: dict(owner),
                "get_collaboration_conversation": lambda conversation_id: {"id": conversation_id},
                "assert_user_can_participate_in_collaboration_conversation": lambda *args, **kwargs: {},
                "get_collaboration_message": lambda message_id: copy.deepcopy(ghost),
                "cosmos_collaboration_messages_container": shared_messages,
            }),
            (collaboration_functions, {"cosmos_collaboration_messages_container": shared_messages}),
            (mcp_tools, {"cosmos_messages_container": messages}),
        ):
            for name, value in replacements.items():
                stack.enter_context(patch.object(module, name, value))

        conversations_app = Flask("soft-delete-conversations")
        conversations_app.config["TESTING"] = True
        conversations.register_route_backend_conversations(conversations_app)
        chats_app = Flask("soft-delete-chats")
        chats_app.config["TESTING"] = True
        chats.register_route_backend_chats(chats_app)
        collaboration_app = Flask("soft-delete-collaboration")
        collaboration_app.config["TESTING"] = True
        collaboration_routes.register_route_backend_collaboration(collaboration_app)
        client = conversations_app.test_client()

        def visible_ids():
            response = client.get(f"/api/get_messages?conversation_id={CONVERSATION}")
            check(response.status_code == 200, f"get_messages failed: {response.status_code} {response.get_data(as_text=True)}")
            return [item["id"] for item in response.get_json()["messages"]]

        def scenario(function):
            """Run one scenario now and record its failure, so every failing path is reported."""
            try:
                function()
            except Exception as error:
                failures.append(f"{function.__name__}: {type(error).__name__}: {error}")
            finally:
                settings["enable_conversation_archiving"] = True
            return function

        @scenario
        def helper_semantics():
            live = message("live", "user", "Hello", "2026-01-01T00:00:01")
            gone = soft_deleted(message("gone", "user", "Bye", "2026-01-01T00:00:02"))
            check(is_soft_deleted_message(gone) and not is_soft_deleted_message(live), "Soft-delete predicate is wrong")
            check(not is_soft_deleted_message({"metadata": {"is_deleted": "true"}}), "Only a real True marks deletion")
            check(not is_soft_deleted_message(None) and not is_soft_deleted_message({"metadata": None}), "Malformed input")
            check([item["id"] for item in exclude_soft_deleted_messages([live, gone])] == ["live"], "Filter kept a deleted message")
            stripped = strip_soft_delete_metadata(dict(gone["metadata"]))
            check(not {"is_deleted", "deleted_by_user_id", "deleted_timestamp"} & set(stripped), "Deletion markers were kept")
            check(stripped.get("masked") is True, "Stripping deletion markers must not touch masks")

        @scenario
        def message_list_excludes_deleted():
            messages.reset([
                message("q0", "user", "Kept question", "2026-01-01T00:00:01", "t0"),
                message("a0", "assistant", "Kept answer", "2026-01-01T00:00:02", "t0"),
                soft_deleted(message("q9", "user", "Deleted question", "2026-01-01T00:00:03", "t9")),
                soft_deleted(message("a9", "assistant", "Deleted answer", "2026-01-01T00:00:04", "t9")),
            ])
            check(visible_ids() == ["q0", "a0"], "Soft-deleted messages were returned and would render as masked")

        @scenario
        def deleting_an_answer_promotes_nothing():
            messages.reset(retried_turn())
            response = client.delete("/api/message/a2", json={"delete_thread": False})
            check(response.status_code == 200, f"Delete failed: {response.get_data(as_text=True)}")
            check(response.get_json()["archived"] is True, "Archiving was not used")
            check(is_soft_deleted_message(messages.get("a2")), "The answer was not soft-deleted")
            check("a2" in archive.items, "The deleted answer was not archived")
            flags = active_flags(messages)
            check(flags["q1"] is False and flags["a1"] is False, "Deleting an answer re-activated an older attempt")
            check(flags["q2"] is True, "The latest question lost its active attempt")
            check(visible_ids() == ["q2"], "After deleting an answer, only its question should remain")

        @scenario
        def deleting_a_deleted_message_is_not_found():
            messages.reset([soft_deleted(message("a2", "assistant", "Gone", "2026-01-01T00:00:04", "t1", 2))])
            response = client.delete("/api/message/a2", json={"delete_thread": False})
            check(response.status_code == 404, "A soft-deleted message could be deleted again")

        @scenario
        def permanent_delete_of_an_answer_promotes_nothing():
            settings["enable_conversation_archiving"] = False
            messages.reset(retried_turn())
            response = client.delete("/api/message/a2", json={"delete_thread": False})
            check(response.status_code == 200 and response.get_json()["archived"] is False, "Hard delete failed")
            check("a2" not in messages.items, "The answer was not removed")
            check(active_flags(messages)["q1"] is False, "A hard delete of an answer re-activated an older attempt")

        @scenario
        def deleting_the_question_promotes_the_other_attempt_alone():
            messages.reset(retried_turn())
            response = client.delete("/api/message/q2", json={"delete_thread": False})
            check(response.status_code == 200, f"Question delete failed: {response.get_data(as_text=True)}")
            flags = active_flags(messages)
            check(flags["q1"] is True and flags["a1"] is True, "The remaining attempt was not promoted")
            check(flags["a2"] is False, "The deleted question's answer stayed active beside the promoted attempt")
            check(visible_ids() == ["q1", "a1"], "Promotion left the thread showing two attempts")

        @scenario
        def a_deleted_attempt_is_never_promoted():
            # With no other question left, the answer whose question was deleted is all that
            # remains of the turn.
            messages.reset(retried_turn(deleted_first_question=True))
            response = client.delete("/api/message/q2", json={"delete_thread": False})
            check(response.status_code == 200, "Question delete failed")
            check(active_flags(messages)["q1"] is False, "A soft-deleted attempt was promoted")
            check(visible_ids() == ["a2"], "A deleted attempt came back after promotion")

        @scenario
        def attempt_switching_skips_deleted_attempts():
            messages.reset([
                soft_deleted(message("q1", "user", "Deleted wording", "2026-01-01T00:00:01", "t1", 1, False)),
                soft_deleted(message("a1", "assistant", "Deleted answer", "2026-01-01T00:00:02", "t1", 1, False)),
                message("q2", "user", "Second wording", "2026-01-01T00:00:03", "t1", 2, True),
                message("a2", "assistant", "Second answer", "2026-01-01T00:00:04", "t1", 2, True),
                message("q3", "user", "Third wording", "2026-01-01T00:00:05", "t1", 3, False),
                message("a3", "assistant", "Third answer", "2026-01-01T00:00:06", "t1", 3, False),
            ])
            response = client.post("/api/message/a2/switch-attempt", json={"direction": "next"})
            payload = response.get_json()
            check(response.status_code == 200, f"Switch failed: {payload}")
            check(payload["available_attempts"] == [2, 3], f"Deleted attempts were offered: {payload}")
            check(payload["target_attempt"] == 3 and visible_ids() == ["q3", "a3"], "Switching did not reach attempt 3")
            response = client.post("/api/message/a3/switch-attempt", json={"direction": "next"})
            check(response.get_json()["target_attempt"] == 2, "Switching wrapped onto a deleted attempt")
            check(visible_ids() == ["q2", "a2"], "A deleted attempt was shown after switching")
            response = client.post("/api/message/a1/switch-attempt", json={"direction": "next"})
            check(response.status_code == 404, "A soft-deleted message could drive attempt switching")

        @scenario
        def retry_does_not_inherit_deletion():
            messages.reset(retried_turn(deleted_first_question=True))
            response = client.post("/api/message/a2/retry", json={})
            payload = response.get_json()
            check(response.status_code == 200, f"Retry failed: {payload}")
            retried = messages.get(payload["user_message_id"])
            check(not is_soft_deleted_message(retried), "The retried question was created already deleted")
            check(retried["metadata"].get("masked") is not True, "The retried question inherited the deletion mask")
            check(retried["content"] == "Second wording", "Retry replayed the deleted question")
            check(payload["chat_request"]["message"] == "Second wording", "Retry sent the deleted question to the model")
            check(client.post("/api/message/q1/retry", json={}).status_code == 404, "A deleted message could be retried")

        @scenario
        def edit_does_not_inherit_deletion():
            messages.reset(retried_turn(deleted_first_question=True))
            response = client.post("/api/message/q2/edit", json={"content": "Edited wording"})
            payload = response.get_json()
            check(response.status_code == 200, f"Edit failed: {payload}")
            edited = messages.get(payload["user_message_id"])
            check(not is_soft_deleted_message(edited), "The edited question was created already deleted")
            check(edited["metadata"].get("masked") is not True, "The edited question inherited the deletion mask")
            check(edited["content"] == "Edited wording", "The edit lost its content")
            response = client.post("/api/message/q1/edit", json={"content": "Bring it back"})
            check(response.status_code == 404, "A deleted message could be edited")

        @scenario
        def personal_mask_route_keeps_the_deletion_mask():
            messages.reset([
                message("q0", "user", "Kept question", "2026-01-01T00:00:01"),
                soft_deleted(message("q9", "user", "Deleted question", "2026-01-01T00:00:02")),
            ])
            chats_client = chats_app.test_client()
            response = chats_client.post(
                "/api/message/q9/mask", json={"action": "unmask_message", "conversation_id": CONVERSATION},
            )
            check(response.status_code == 404, f"A deleted message could be unmasked: {response.status_code}")
            check(messages.get("q9")["metadata"]["masked"] is True, "The deleted message's mask was cleared")
            response = chats_client.post(
                "/api/message/q0/mask", json={"action": "mask_all", "conversation_id": CONVERSATION},
            )
            check(response.status_code == 200, f"Masking a live message broke: {response.get_data(as_text=True)}")
            check(messages.get("q0")["metadata"]["masked"] is True, "The live message was not masked")

        @scenario
        def shared_mask_route_keeps_the_deletion_mask():
            shared_messages.reset()
            response = collaboration_app.test_client().post(
                f"/api/collaboration/conversations/{SHARED_CONVERSATION}/messages/ghost/mask",
                json={"action": "unmask_message"},
            )
            check(response.status_code == 404, f"A deleted shared copy could be unmasked: {response.status_code}")
            check(not shared_messages.items, "The deleted shared copy was written")

        @scenario
        def forks_do_not_copy_deleted_messages():
            fork_source = [
                soft_deleted(message("q9", "user", "Deleted question", "2026-01-01T00:00:01", "t9")),
                soft_deleted(message("a9", "assistant", "Deleted answer", "2026-01-01T00:00:02", "t9")),
                message("q0", "user", "Kept question", "2026-01-01T00:00:03", "t0"),
                message("a0", "assistant", "Kept answer", "2026-01-01T00:00:04", "t0"),
            ]
            forked = operations._collect_fork_documents(fork_source, "a0")
            check([item["id"] for item in forked] == ["q0", "a0"], "A fork copied soft-deleted messages")
            try:
                operations._collect_fork_documents(fork_source, "a9")
            except LookupError:
                return
            raise AssertionError("A fork could start from a deleted message")

        @scenario
        def sharing_does_not_copy_deleted_messages():
            source_messages = [
                message("q0", "user", "Kept question", "2026-01-01T00:00:01"),
                message("a0", "assistant", "Kept answer", "2026-01-01T00:00:02"),
                soft_deleted(message("q9", "user", "Deleted question", "2026-01-01T00:00:03")),
            ]
            for copier in (
                collaboration_functions._copy_legacy_personal_messages_to_collaboration,
                collaboration_functions._copy_legacy_group_messages_to_collaboration,
            ):
                shared_messages.reset()
                copied = copier("source-1", SHARED_CONVERSATION, owner, raw_messages=copy.deepcopy(source_messages))
                check(len(copied) == 2 and len(shared_messages.items) == 2, f"{copier.__name__} copied deleted messages")
                check(not any(is_soft_deleted_message(item) for item in shared_messages.items.values()), "A deleted copy was stored")

        @scenario
        def shared_list_hides_existing_deleted_copies():
            shared_messages.reset([
                message("s1", "user", "Shared question", "2026-01-01T00:00:01", conversation=SHARED_CONVERSATION),
                ghost,
            ])
            listed = collaboration_functions.list_collaboration_messages(SHARED_CONVERSATION)
            check([item["id"] for item in listed] == ["s1"], "A shared conversation listed a deleted copy")

        @scenario
        def search_skips_deleted_messages():
            searchable = FakeContainer([
                message("q0", "user", "quarterly budget review", "2026-01-01T00:00:01"),
                soft_deleted(message("q9", "user", "quarterly budget secret", "2026-01-01T00:00:02")),
            ])
            matches = conversations._query_matching_messages(
                searchable, "quarterly budget", conversations._normalize_search_match_mode(None),
            )
            check([item["id"] for item in matches] == ["q0"], "Search matched a deleted message")

        @scenario
        def mcp_skips_deleted_messages():
            messages.reset([
                message("q0", "user", "Kept question", "2026-01-01T00:00:01"),
                message("a0", "assistant", "Kept answer", "2026-01-01T00:00:02"),
                soft_deleted(message("q9", "user", "Deleted question", "2026-01-01T00:00:03")),
            ])
            mcp_ids = [item["id"] for item in mcp_tools._load_legacy_messages(CONVERSATION)]
            check(mcp_ids == ["q0", "a0"], "MCP read a deleted message")

        @scenario
        def conversation_summary_skips_deleted_messages():
            messages.reset([
                message("q0", "user", "Kept question", "2026-01-01T00:00:01"),
                message("a0", "assistant", "Kept answer", "2026-01-01T00:00:02"),
                soft_deleted(message("q9", "user", "Deleted question", "2026-01-01T00:00:03")),
            ])
            captured = {}

            def fake_summary(**kwargs):
                captured["messages"] = kwargs["messages"]
                return {"summary": "ok"}

            with patch.object(conversation_export, "generate_conversation_summary", fake_summary):
                response = client.post(f"/api/conversations/{CONVERSATION}/summary", json={})
            check(response.status_code == 200, f"Summary failed: {response.get_data(as_text=True)}")
            summary_text = json.dumps(captured["messages"])
            check("Kept question" in summary_text, "The summary lost a live message")
            check("Deleted question" not in summary_text, "The summary read a deleted message")

        @scenario
        def model_history_skips_deleted_messages():
            prompts = []

            def create(**kwargs):
                prompts.append(json.dumps(kwargs["messages"]))
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Earlier: kept turn."))])

            gpt_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            history = [
                message("h1", "user", "Kept older question", "2026-01-01T00:00:01"),
                message("h2", "assistant", "Kept older answer", "2026-01-01T00:00:02"),
                soft_deleted(message("h3", "user", "Deleted secret question", "2026-01-01T00:00:03")),
                soft_deleted(message("h4", "assistant", "Deleted secret answer", "2026-01-01T00:00:04")),
                message("h5", "assistant", "Recent answer", "2026-01-01T00:00:05"),
                message("h6", "user", "Current question", "2026-01-01T00:00:06"),
            ]
            with Flask("soft-delete-history").test_request_context("/"):
                segments = chats.build_conversation_history_segments(
                    history,
                    2,
                    enable_summarize_older_messages=True,
                    gpt_client=gpt_client,
                    gpt_model="offline-model",
                    user_message_id="h6",
                    fallback_user_message="Current question",
                )
            check(prompts and "Kept older question" in prompts[0], "Older messages were not summarized")
            check("Deleted secret" not in prompts[0], "A deleted message was summarized for the model")
            recent_text = json.dumps(segments["history_messages"])
            check("Deleted secret" not in recent_text, "A deleted message reached the model history")
            check("Recent answer" in recent_text and "Current question" in recent_text, "The recent window lost live messages")
            check(segments["debug_info"]["stored_total_messages"] == 4, "Deleted messages still counted toward history")

        @scenario
        def orchestration_history_skips_deleted_messages():
            deleted_unmasked = {"role": "user", "content": "Deleted", "metadata": {"is_deleted": True, "thread_info": {}}}
            check(orchestration_context.normalize_history_message(deleted_unmasked) is None, "Orchestration read a deleted message")
            live = {"role": "user", "content": "Live", "metadata": {"thread_info": {}}}
            check(orchestration_context.normalize_history_message(live) is not None, "Orchestration dropped a live message")

        @scenario
        def recent_replies_skip_deleted_ones():
            messages.reset([
                message("r1", "assistant", "Older live reply", "2026-01-01T00:00:01"),
                soft_deleted(message("r2", "assistant", "Newer deleted reply", "2026-01-01T00:00:02")),
            ])
            recent = chats._read_recent_assistant_messages(CONVERSATION, 1)
            check([item["id"] for item in recent] == ["r1"], "Recent replies included a deleted one or counted it toward TOP")
            check(NOT_SOFT_DELETED in messages.queries[-1], "Recent replies are not filtered in the query")

        @scenario
        def shared_grounding_skips_a_deleted_request():
            shared_messages.reset([
                message("s1", "user", "Draw the live flow", "2026-01-01T00:00:01", conversation=SHARED_CONVERSATION),
                ghost,
            ])
            grounding = collaboration_routes._find_collaboration_originating_request(
                SHARED_CONVERSATION, {"timestamp": "2026-01-01T00:10:00"},
            )
            check(grounding == "Draw the live flow", f"Grounding used a deleted request: {grounding!r}")
            check(NOT_SOFT_DELETED in shared_messages.queries[-1], "Shared grounding is not filtered in the query")

    if failures:
        print(PROBE_FAILED)
        for failure in failures:
            print(f" - {failure}")
        raise SystemExit(1)
    print(PROBE_OK)


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------

def _run_probe_process(optimized=False):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend([str(Path(__file__).resolve()), PROBE_FLAG])
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        env=environment,
    )
    if result.returncode != 0 or PROBE_OK not in result.stdout:
        failures = result.stdout[result.stdout.find(PROBE_FAILED):] if PROBE_FAILED in result.stdout else ""
        raise AssertionError(
            f"Probe failed (optimized={optimized}, exit={result.returncode}).\n"
            f"{failures or 'STDOUT tail:' + chr(10) + result.stdout[-4000:]}\n"
            f"STDERR tail:\n{result.stderr[-6000:]}"
        )


def test_soft_deleted_messages_stay_deleted_with_real_modules():
    """Drive the real modules in a fresh process, normally and under python -O."""
    print("Testing soft-deleted message visibility with real modules...")
    _run_probe_process(optimized=False)
    _run_probe_process(optimized=True)
    print("Soft-deleted messages stayed deleted on every path.")
    return True


def _slice(source, start_marker, end_marker):
    start = source.index(start_marker)
    return source[start:source.index(end_marker, start)]


def test_v2_client_and_personal_grounding_contracts():
    """The V2 store filters deleted messages, attempts count by position, grounding skips deleted."""
    print("Testing V2 client and personal grounding contracts...")
    sys.path.insert(0, str(ROOT / "functional_tests"))
    from test_support.versioning import assert_app_version_at_least

    assert_app_version_at_least("0.261.253")

    helper = (V2_SRC / "lib" / "deletedMessages.ts").read_text(encoding="utf-8")
    check("message?.metadata?.is_deleted === true" in helper, "isDeletedMessage must test is_deleted === true")
    check("export function withoutDeletedMessages" in helper, "withoutDeletedMessages is missing")

    store = (V2_SRC / "stores" / "chatStore.ts").read_text(encoding="utf-8")
    select_block = _slice(store, "selectConversation: async", "\n    },\n")
    reload_block = _slice(store, "reloadMessages: async", "\n    },\n")
    for name, block in (("selectConversation", select_block), ("reloadMessages", reload_block)):
        check("withoutDeletedMessages(loadedMessages)" in block, f"{name} does not drop deleted messages")
        check("messages: messages ?? []" not in block, f"{name} still stores the unfiltered list")

    threads = (V2_SRC / "lib" / "threads.ts").read_text(encoding="utf-8")
    attempt_block = _slice(threads, "export function attemptState", "\n}\n")
    check("known.indexOf(current)" in attempt_block, "Attempts must be counted by position in the reported set")
    check("current: position + 1" in attempt_block, "The attempt label must use the position, not the attempt number")
    check("total: known.length" in attempt_block, "The total must come from the reported set")

    chats_source = (APP_ROOT / "route_backend_chats.py").read_text(encoding="utf-8")
    grounding = _slice(chats_source, "def _find_originating_user_request", "def _answer_raced_block_submission")
    check("NOT_SOFT_DELETED_COSMOS_FILTER" in grounding, "Personal diagram grounding can read a deleted request")

    conversations_source = (APP_ROOT / "route_backend_conversations.py").read_text(encoding="utf-8")
    check("'soft_deleted_message_policy_version': 1" in conversations_source, "Cached search results are not re-keyed")

    legacy = (APP_ROOT / "static" / "js" / "chat" / "chat-messages.js").read_text(encoding="utf-8")
    check("msg.metadata.is_deleted === true" in legacy, "The classic client stopped skipping deleted messages")

    print("V2 client and grounding contracts hold.")
    return True


if __name__ == "__main__":
    if PROBE_FLAG in sys.argv:
        run_probe()
        sys.exit(0)

    tests = [
        test_v2_client_and_personal_grounding_contracts,
        test_soft_deleted_messages_stay_deleted_with_real_modules,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:
            import traceback

            print(f"Test failed: {error}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
