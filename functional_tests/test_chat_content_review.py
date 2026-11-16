# test_chat_content_review.py
"""
Functional tests for private unchecked-chat review and durable reply removal.
Version: 0.261.127
Implemented in: 0.261.127

Use revision-aware in-memory Cosmos adapters and the real screening evaluator.
No Azure connection, production message, or model request is used.
"""

import copy
import ast
import json
import logging
import sys
import unittest
from contextlib import ExitStack
from datetime import datetime
from functools import wraps
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

from azure.core.exceptions import AzureError
from azure.cosmos import exceptions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError, CosmosResourceExistsError, CosmosResourceNotFoundError,
)
from flask import Blueprint, Flask, jsonify, request, session


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from content_screening.contracts import ScreeningValidationError
from content_screening.policies import STARTER_RULE_TEMPLATES, default_policy
from functions_chat_content_checks import (
    CHECK_METADATA, REMOVED_REPLY_MESSAGE, attach_chat_check, evaluate_chat_content,
    retract_message_content, strip_private_chat_checks,
)
from functions_chat_content_review import (
    ChatContentReviewConflict, ChatReviewStores, checked_history_messages,
    list_unchecked_chat_content, persist_chat_reply, recheck_chat_message,
    refresh_checked_message, retracted_stream_payload,
    content_checks_report_enabled, patch_chat_message_metadata,
)
import functions_chat_content_review as review
import content_screening.repository as screening_repository


SETTINGS = {
    "enable_content_screening": True,
    "enable_content_screening_chat_input": True,
    "enable_content_screening_chat_output": True,
}


def baseline():
    policy = default_policy()
    policy["enabled"] = True
    policy["rules"] = [copy.deepcopy(STARTER_RULE_TEMPLATES["email"])]
    return policy


def check(text, checkpoint, *, user_id, settings, required_scanners):
    result = evaluate_chat_content(
        text, checkpoint, settings, baseline_loader=baseline, required_scanners=required_scanners,
    )
    result.metadata["actor_user_id"] = user_id
    return result


class MemoryContainer:
    def __init__(self, documents=()):
        self.items = {}
        self.revision = 0
        self.queries = []
        self.before_replace = None
        for document in documents:
            self.create_item(document)

    def read_item(self, item, partition_key):
        value = self.items.get((partition_key, item))
        if value is None:
            raise CosmosResourceNotFoundError(status_code=404, message="missing")
        return copy.deepcopy(value)

    def create_item(self, body):
        key = (body.get("conversation_id", body.get("id")), body["id"])
        if key in self.items:
            raise CosmosResourceExistsError(status_code=409, message="exists")
        self.revision += 1
        saved = {**copy.deepcopy(body), "_etag": str(self.revision)}
        self.items[key] = saved
        return copy.deepcopy(saved)

    def replace_item(self, item, body, etag, match_condition):
        key = (body.get("conversation_id", body.get("id")), item)
        if self.before_replace:
            callback, self.before_replace = self.before_replace, None
            callback()
        if self.items[key]["_etag"] != etag:
            raise CosmosAccessConditionFailedError(status_code=412, message="changed")
        self.revision += 1
        saved = {**copy.deepcopy(body), "_etag": str(self.revision)}
        self.items[key] = saved
        return copy.deepcopy(saved)

    def query_items(self, query, parameters, **kwargs):
        self.queries.append((query, copy.deepcopy(parameters), kwargs))
        args = {item["name"]: item["value"] for item in parameters}
        rows = list(self.items.values())
        if "chat_content_checks.status = 'not_checked'" in query:
            rows = [
                item for item in rows
                if item.get("metadata", {}).get(CHECK_METADATA, {}).get("status") == "not_checked"
                and item["metadata"][CHECK_METADATA].get("decision") == "allow_unchecked"
            ]
        if "@checkpoint" in args:
            rows = [item for item in rows if item["metadata"][CHECK_METADATA]["checkpoint"] == args["@checkpoint"]]
        if "@scanner" in args:
            rows = [
                item for item in rows
                if any(
                    scanner["scanner"] == args["@scanner"] and not scanner["complete"]
                    for scanner in item["metadata"][CHECK_METADATA]["scanners"]
                )
            ]
        if "NOT IS_DEFINED(c.metadata.source_message_id)" in query:
            rows = [item for item in rows if "source_message_id" not in item.get("metadata", {})]
        if "c.metadata.source_conversation_id = @conversation" in query:
            rows = [
                item for item in rows
                if item.get("metadata", {}).get("source_conversation_id") == args["@conversation"]
                and item.get("metadata", {}).get("source_message_id") == args["@message"]
            ]
        rows = sorted(rows, key=lambda item: item["id"])
        if "@after" in args:
            rows = [item for item in rows if item["id"] > args["@after"]]
        return iter(copy.deepcopy(rows[:args.get("@page_limit", len(rows))]))


def unchecked_message(message_id="reply", text="alice@example.test", role="assistant"):
    checkpoint = "chat_output" if role == "assistant" else "chat_input"
    result = evaluate_chat_content(text, checkpoint, SETTINGS)
    result.metadata["actor_user_id"] = "owner"
    document = {
        "id": message_id, "conversation_id": "conversation", "role": role,
        "content": text, "timestamp": "2026-01-01T00:00:00+00:00",
        "metadata": {"thread_info": {"thread_id": "thread"}},
    }
    attach_chat_check(document, result)
    return document


class ChatContentReviewTests(unittest.TestCase):
    def setUp(self):
        self.messages = MemoryContainer([unchecked_message()])
        self.conversations = MemoryContainer([{"id": "conversation", "user_id": "owner"}])
        self.shared = MemoryContainer()
        self.stores = ChatReviewStores(
            self.messages, self.conversations, self.shared, MemoryContainer(), MemoryContainer(),
        )
        self.on_retracted = Mock()

    def recheck(self, **overrides):
        original = self.messages.read_item("reply", "conversation")
        arguments = {
            "source": "chat", "conversation_id": "conversation", "message_id": "reply",
            "etag": original["_etag"], "actor_id": "reviewer", "settings": SETTINGS,
            "stores": self.stores, "checker": check, "on_retracted": self.on_retracted,
        }
        arguments.update(overrides)
        return recheck_chat_message(**arguments)

    def test_admin_list_is_bounded_and_contains_no_message_body(self):
        page = list_unchecked_chat_content(stores=self.stores, page_size=1)
        self.assertEqual(len(page["items"]), 1)
        self.assertNotIn("alice@example.test", json.dumps(page))
        self.assertEqual(page["items"][0]["message_id"], "reply")
        self.assertIn("SELECT TOP @page_limit", self.messages.queries[0][0])
        self.assertLessEqual(self.messages.queries[0][2]["max_item_count"], 2)

    def test_pagination_visits_both_sources_without_repeating_records(self):
        self.messages.create_item(unchecked_message("second"))
        self.shared.create_item(unchecked_message("shared"))
        continuation = None
        identifiers = []
        for _ in range(4):
            page = list_unchecked_chat_content(stores=self.stores, page_size=1, continuation=continuation)
            identifiers.extend(item["message_id"] for item in page["items"])
            continuation = page["continuation"]
            if continuation is None:
                break
        self.assertEqual(identifiers, ["reply", "second", "shared"])
        self.assertIsNone(continuation)

    def test_invalid_page_sizes_and_changed_cursor_filters_are_rejected(self):
        for size in (0, -1, True, 101, "25"):
            with self.subTest(size=size), self.assertRaises(ScreeningValidationError):
                list_unchecked_chat_content(stores=self.stores, page_size=size)
        page = list_unchecked_chat_content(stores=self.stores, page_size=1)
        with self.assertRaises(ScreeningValidationError):
            list_unchecked_chat_content(
                stores=self.stores, page_size=1, continuation=page["continuation"], scanner="content_safety",
            )

    def test_recheck_retracts_flagged_reply_and_keeps_only_safe_content(self):
        outcome = self.recheck()
        stored = self.messages.read_item("reply", "conversation")
        self.assertTrue(outcome["removed"])
        self.assertEqual(stored["role"], "safety")
        self.assertEqual(stored["content"], REMOVED_REPLY_MESSAGE)
        self.assertNotIn("alice@example.test", json.dumps(stored))
        self.assertEqual(stored["metadata"][CHECK_METADATA]["initial_check"]["status"], "not_checked")
        self.assertEqual(stored["metadata"][CHECK_METADATA]["rechecked_by"], "reviewer")
        self.on_retracted.assert_called_once()
        self.assertEqual(self.on_retracted.call_args.args[1]["_etag"], stored["_etag"])
        self.assertEqual(len(self.stores.safety.items), 1)

    def test_clean_recheck_removes_message_from_unchecked_list(self):
        self.messages = MemoryContainer([unchecked_message(text="An ordinary answer.")])
        self.stores.messages = self.messages
        outcome = self.recheck()
        page = list_unchecked_chat_content(stores=self.stores)
        self.assertFalse(outcome["removed"])
        self.assertEqual(outcome["check"]["status"], "passed")
        self.assertEqual(page["items"], [])
        self.on_retracted.assert_not_called()

    def test_recheck_failure_stays_quiet_and_retryable_even_with_strict_new_chat_policy(self):
        failure_settings = {**SETTINGS, "chat_content_scan_failure_action": "block"}
        failure = lambda text, checkpoint, **kwargs: evaluate_chat_content(text, checkpoint, failure_settings)
        outcome = self.recheck(checker=failure, settings=failure_settings)
        stored = self.messages.read_item("reply", "conversation")
        page = list_unchecked_chat_content(stores=self.stores)
        self.assertFalse(outcome["removed"])
        self.assertEqual(stored["content"], "alice@example.test")
        self.assertEqual(outcome["check"]["decision"], "allow_unchecked")
        self.assertEqual(len(page["items"]), 1)
        self.on_retracted.assert_not_called()

    def test_stale_recheck_does_not_invoke_scanner(self):
        checker = Mock()
        with self.assertRaises(ChatContentReviewConflict):
            self.recheck(etag="old", checker=checker)
        checker.assert_not_called()

    def test_changed_text_cannot_receive_clearance_for_an_old_snapshot(self):
        original = self.messages.read_item("reply", "conversation")
        modified = {**original, "content": "Changed since the failed check"}
        self.messages.replace_item("reply", modified, original["_etag"], None)
        with self.assertRaises(ChatContentReviewConflict):
            self.recheck()

    def test_later_user_input_finding_does_not_delete_the_old_user_message(self):
        self.messages = MemoryContainer([unchecked_message(role="user")])
        self.stores.messages = self.messages
        outcome = self.recheck()
        stored = self.messages.read_item("reply", "conversation")
        model_history = checked_history_messages([stored], stores=self.stores, for_model=True)
        self.assertFalse(outcome["removed"])
        self.assertEqual(stored["content"], "alice@example.test")
        self.assertEqual(stored["role"], "user")
        self.assertEqual(model_history, [])

    def test_cached_history_and_replay_resolve_the_current_removal(self):
        stale = self.messages.read_item("reply", "conversation")
        self.recheck()
        current = refresh_checked_message(strip_private_chat_checks(stale), stores=self.stores)
        replay = retracted_stream_payload("conversation", "reply", stores=self.stores)
        self.assertEqual(current["content"], REMOVED_REPLY_MESSAGE)
        self.assertTrue(replay["replace_content"])
        self.assertNotIn("alice@example.test", json.dumps(replay))

    def test_stale_shared_mirror_reads_the_current_canonical_removal(self):
        mirror = unchecked_message("mirror")
        mirror["conversation_id"] = "shared-conversation"
        mirror["message_kind"] = "ai_response"
        mirror["metadata"].update({
            "sender": {"user_id": "assistant"}, "source_conversation_id": "conversation",
            "source_message_id": "reply",
        })
        self.shared.create_item(mirror)
        self.recheck()
        projected = refresh_checked_message(
            strip_private_chat_checks(mirror), source="shared", stores=self.stores,
        )
        self.assertEqual(projected["id"], "mirror")
        self.assertEqual(projected["conversation_id"], "shared-conversation")
        self.assertEqual(projected["content"], REMOVED_REPLY_MESSAGE)
        self.assertNotIn("alice@example.test", json.dumps(projected))

    def test_late_writer_cannot_restore_a_retracted_reply(self):
        stale = self.messages.read_item("reply", "conversation")
        self.recheck()
        result = persist_chat_reply(self.messages, stale)
        current = self.messages.read_item("reply", "conversation")
        self.assertEqual(result["role"], "safety")
        self.assertEqual(current["content"], REMOVED_REPLY_MESSAGE)

    def test_thread_metadata_updates_preserve_a_newer_retraction(self):
        stale = self.messages.read_item("reply", "conversation")
        stale["metadata"]["thread_info"]["active_thread"] = False
        self.recheck()
        updated = patch_chat_message_metadata(self.messages, stale)
        self.assertEqual(updated["role"], "safety")
        self.assertEqual(updated["content"], REMOVED_REPLY_MESSAGE)
        self.assertFalse(updated["metadata"]["thread_info"]["active_thread"])

    def test_retraction_propagates_to_shared_messages_summaries_thoughts_and_streams(self):
        mirror = unchecked_message("mirror")
        mirror["conversation_id"] = "shared-conversation"
        mirror["metadata"].update({
            "source_conversation_id": "conversation", "source_message_id": "reply",
            "sender": {"user_id": "assistant"},
        })
        self.shared.create_item(mirror)
        self.stores.shared_conversations.create_item({
            "id": "shared-conversation", "summary": "private-summary", "last_message_preview": "private-preview",
        })
        publish = Mock()
        invalidate = Mock()
        delete_notes = Mock()
        stream = Mock()
        modules = {}
        for name, values in {
            "functions_collaboration": {
                "publish_collaboration_event": publish,
                "serialize_collaboration_message": strip_private_chat_checks,
            },
            "functions_conversation_cache": {"invalidate_conversation_cache_for_item": invalidate},
            "functions_thoughts": {"delete_scoped_thoughts_for_message": delete_notes},
            "route_backend_chats": {"CHAT_STREAM_REGISTRY": Mock(get_session=Mock(return_value=stream))},
        }.items():
            module = ModuleType(name)
            module.__dict__.update(values)
            modules[name] = module
        with patch.dict(sys.modules, modules):
            outcome = self.recheck(on_retracted=review.propagate_chat_retraction)
        mirrored = self.shared.read_item("mirror", "shared-conversation")
        shared_conversation = self.stores.shared_conversations.read_item("shared-conversation", "shared-conversation")
        self.assertTrue(outcome["removed"])
        self.assertEqual(mirrored["content"], REMOVED_REPLY_MESSAGE)
        self.assertIsNone(shared_conversation["summary"])
        self.assertEqual(shared_conversation["last_message_preview"], "")
        self.assertEqual(invalidate.call_count, 2)
        delete_notes.assert_called_once_with("conversation", "reply", "owner")
        stream.retract.assert_called_once()
        self.assertEqual(publish.call_args.args[1]["event_type"], "collaboration.message.updated")
        self.assertNotIn("alice@example.test", json.dumps(publish.call_args.args[1]))

    def test_concurrent_retraction_wins_over_a_writer_that_already_read(self):
        stale = self.messages.read_item("reply", "conversation")
        decision = check(
            stale["content"], "chat_output", user_id="owner", settings=SETTINGS,
            required_scanners=["content_screening"],
        )

        def retract_during_write():
            replacement = retract_message_content(stale, decision)
            self.messages.replace_item("reply", replacement, stale["_etag"], None)

        self.messages.before_replace = retract_during_write
        result = persist_chat_reply(self.messages, stale)
        self.assertEqual(result["role"], "safety")
        self.assertEqual(result["content"], REMOVED_REPLY_MESSAGE)


class ChatContentReviewRouteTests(unittest.TestCase):
    """Execute the actual route bodies and decorators with isolated auth/storage seams."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = dict(SETTINGS)
        settings_module = ModuleType("functions_settings")
        settings_module.get_settings = lambda: self.settings
        logging_module = ModuleType("functions_appinsights")
        logging_module.log_event = Mock()
        self.stack.enter_context(patch.dict(sys.modules, {
            "functions_settings": settings_module, "functions_appinsights": logging_module,
        }))
        self.messages = MemoryContainer([unchecked_message()])
        self.stores = ChatReviewStores(
            self.messages, MemoryContainer([{"id": "conversation", "user_id": "owner"}]),
            MemoryContainer(), MemoryContainer(), MemoryContainer(),
        )
        self.stack.enter_context(patch.object(review, "get_chat_review_stores", return_value=self.stores))
        self.stack.enter_context(patch.object(review, "propagate_chat_retraction"))
        self.stack.enter_context(patch.object(
            screening_repository, "get_repository",
            return_value=Mock(get_policy=Mock(return_value={"policy": baseline()})),
        ))

        def login(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                if not session.get("user"):
                    return jsonify({"error": "Sign in required."}), 401
                return function(*args, **kwargs)
            return wrapped

        def reviewer(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                role = "SafetyViolationAdmin" if self.settings.get("require_member_of_safety_violation_admin") else "Admin"
                if role not in (session.get("user") or {}).get("roles", []):
                    return jsonify({"error": "Not authorized."}), 403
                return function(*args, **kwargs)
            return wrapped

        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="synthetic-chat-check-route")
        blueprint = Blueprint("chat_content_review", __name__)
        self.safety = Mock()
        namespace = {
            "bp": blueprint, "request": request, "jsonify": jsonify, "session": session,
            "datetime": datetime, "logging": logging, "log_event": Mock(), "exceptions": exceptions,
            "login_required": login, "user_required": login, "safety_violation_admin_required": reviewer,
            "swagger_route": lambda **kwargs: lambda function: function, "get_auth_security": lambda: [],
            "content_checks_report_enabled": content_checks_report_enabled,
            "get_settings": lambda: self.settings,
            "list_unchecked_chat_content": list_unchecked_chat_content,
            "recheck_chat_message": recheck_chat_message,
            "ChatContentReviewConflict": ChatContentReviewConflict,
            "ScreeningError": review.ScreeningError, "ScreeningValidationError": ScreeningValidationError,
            "CosmosAccessConditionFailedError": CosmosAccessConditionFailedError,
            "CosmosResourceNotFoundError": CosmosResourceNotFoundError, "AzureError": AzureError,
            "cosmos_safety_container": self.safety,
        }
        source = APP / "route_backend_safety.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_safety")
        names = {
            "chat_check_error", "get_unchecked_chat_content", "recheck_unchecked_chat_content", "update_my_safety_log",
        }
        definitions = [
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_get_safety_session_user_id"
        ] + [node for node in registrar.body if isinstance(node, ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), namespace)
        self.app.register_blueprint(blueprint)
        self.client = self.app.test_client()

    def login(self, roles):
        with self.client.session_transaction() as state:
            state["user"] = {"oid": "owner", "roles": roles}

    def test_queue_rejects_anonymous_and_nonreviewer_requests(self):
        anonymous = self.client.get("/api/safety/chat-checks")
        self.login(["User"])
        user = self.client.get("/api/safety/chat-checks")
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(user.status_code, 403)
        self.assertEqual(self.messages.queries, [])

    def test_dedicated_reviewer_role_is_required_when_configured(self):
        self.settings["require_member_of_safety_violation_admin"] = True
        self.login(["Admin"])
        denied = self.client.get("/api/safety/chat-checks")
        self.login(["SafetyViolationAdmin"])
        allowed = self.client.get("/api/safety/chat-checks")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    def test_recheck_uses_stored_text_and_returns_only_admin_metadata(self):
        self.login(["Admin"])
        listed = self.client.get("/api/safety/chat-checks")
        item = listed.get_json()["items"][0]
        body = {key: item[key] for key in ("source", "conversation_id", "message_id", "etag")}
        response = self.client.post("/api/safety/chat-checks/recheck", json=body)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["removed"])
        self.assertNotIn("alice@example.test", listed.get_data(as_text=True))
        self.assertNotIn("alice@example.test", response.get_data(as_text=True))
        stale = self.client.post("/api/safety/chat-checks/recheck", json=body)
        self.assertEqual(stale.status_code, 409)

    def test_request_cannot_supply_replacement_text_or_override_settings(self):
        self.login(["Admin"])
        message = self.messages.read_item("reply", "conversation")
        response = self.client.post("/api/safety/chat-checks/recheck", json={
            "source": "chat", "conversation_id": "conversation", "message_id": "reply",
            "etag": message["_etag"], "text": "clean", "enable_content_screening": False,
        })
        self.assertEqual(response.status_code, 400)
        current = self.messages.read_item("reply", "conversation")
        self.assertEqual(current["content"], "alice@example.test")

    def test_users_cannot_modify_an_ai_output_incident(self):
        self.login(["User"])
        self.safety.read_item.return_value = {
            "id": "incident", "user_id": "owner", "content_origin": "assistant",
        }
        response = self.client.patch("/api/safety/logs/my/incident", json={"user_notes": "override"})
        self.assertEqual(response.status_code, 404)
        self.safety.upsert_item.assert_not_called()


if __name__ == "__main__":
    unittest.main()
