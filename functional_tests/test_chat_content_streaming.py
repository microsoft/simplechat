# test_chat_content_streaming.py
"""
Functional regressions for content-check streaming and processing-note visibility.
Version: 0.261.471
Implemented in: 0.261.127
Semantic outcome and cancellation diagnostics implemented in: 0.261.341
Atomic Redis publication coverage implemented in: 0.261.467
Cosmos discovery pointer coverage implemented in: 0.261.468
Cosmos single-write content coverage implemented in: 0.261.469
Request-scoped settings reuse implemented in: 0.261.471

Execute the shipped stream session/bridge classes against an isolated cache.
Cold-import probes use real modules with network access blocked.
"""

import ast
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
import inspect
import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import (
    Flask, Response, copy_current_request_context, current_app, g, has_request_context,
    jsonify, request, stream_with_context,
)


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from app_settings_cache import StreamDiscoveryUnavailable, StreamReplayProgress, StreamReplayUnconfirmed
from functions_chat_content_checks import CHECK_METADATA, should_withhold_chat_event, strip_private_chat_checks
from functions_stream_timing import StreamTiming


class Cache:
    StreamDiscoveryUnavailable = StreamDiscoveryUnavailable
    StreamReplayUnconfirmed = StreamReplayUnconfirmed

    def __init__(self):
        self.metadata = {}
        self.events = {}
        self.progress = {}
        self.app_cache_is_using_redis = True
        self.publish_stream_content = None
        self.can_publish_stream_content = None

    def initialize_stream_session_cache(self, key, metadata, **kwargs):
        self.metadata[key] = deepcopy(metadata)
        self.events[key] = []

    def set_stream_session_meta(self, key, metadata, **kwargs):
        self.metadata[key] = deepcopy(metadata)
        return True

    def get_cosmos_stream_discovery(self, key):
        return self.get_stream_session_meta(key)

    def initialize_cosmos_stream_discovery(self, key, submission_id, ttl_seconds):
        self.set_stream_session_meta(key, {"submission_id": submission_id}, ttl_seconds=ttl_seconds)

    def renew_cosmos_stream_discovery(self, key, submission_id, ttl_seconds):
        if key not in self.metadata:
            return "missing"
        return "renewed" if self.metadata[key].get('submission_id') == submission_id else "superseded"

    def renew_cosmos_stream_metadata(self, key, submission_id, ttl_seconds):
        if not self.metadata.get(key, {}).get("active"):
            return "superseded"
        return self.renew_cosmos_stream_discovery(key, submission_id, ttl_seconds)

    def get_stream_session_meta(self, key):
        return deepcopy(self.metadata.get(key))

    def append_stream_session_event(self, key, event, **kwargs):
        self.events.setdefault(key, []).append(event)
        if (chars := kwargs.get("progress_chars")) is not None:
            prior = self.progress.get(key, StreamReplayProgress())
            self.progress[key] = StreamReplayProgress(
                prior.event_count + 1, prior.content_chars + chars, datetime.utcnow().isoformat(),
            )

    def get_cosmos_stream_progress(self, key, *, shared=False):
        return self.progress.get(key, StreamReplayProgress())

    def get_stream_session_events(self, key, start_index=0):
        return list(self.events.get(key, [])[start_index:])


def stream_classes(cache, authoritative):
    source = APP / "route_backend_chats.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {
        "BackgroundStreamBridge", "ActiveConversationStreamSession", "ActiveConversationStreamRegistry",
        "_safe_int", "_utcnow_iso", "_parse_iso_datetime", "_truncate_log_text",
        "_build_stream_status_payload", "_extract_sse_event_payload",
    }
    definitions = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            definitions.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and (
                target.id.startswith("STREAM_STATUS_") or target.id in {
                    "STREAM_REPLAY_UNCONFIRMED", "TERMINAL_STREAM_STATUSES",
                }
            ) for target in node.targets
        ):
            definitions.append(node)
    namespace = {
        "queue": queue, "threading": threading, "time": time, "json": json,
        "logging": logging, "datetime": datetime, "app_settings_cache": cache,
        "StreamTiming": StreamTiming,
        "log_event": Mock(), "strip_private_chat_checks": strip_private_chat_checks,
        "log_chat_execution_outcome": Mock(), "VERSION": "0.261.341",
        "retracted_stream_payload": authoritative,
        "ChatAttemptStore": Mock(), "cosmos_conversation_handoffs_container": object(),
        "cosmos_messages_container": object(), "_authorize_personal_conversation_access": Mock(return_value={}),
        "AzureError": AzureError,
    }
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), namespace)
    return SimpleNamespace(**namespace)


def frame(payload):
    return f"data: {json.dumps(payload)}\n\n"


class ChatContentStreamTests(unittest.TestCase):
    def setUp(self):
        self.cache = Cache()
        self.authoritative = Mock(return_value=None)
        self.module = stream_classes(self.cache, self.authoritative)
        self.session = self.module.ActiveConversationStreamSession("owner", "conversation")
        self.session.initialize()
        self.replacement = {
            "done": True, "blocked": True, "role": "safety", "replace_content": True,
            "conversation_id": "conversation", "message_id": "answer",
            "content": "Reply removed.", "full_content": "Reply removed.",
            "metadata": {CHECK_METADATA: {"status": "findings"}},
        }

    def test_background_stream_reuses_turn_settings_for_output_screening(self):
        source = APP / "route_backend_chats.py"
        builder = next(
            node for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(node, ast.FunctionDef) and node.name == "build_background_stream_response"
        )
        read_settings = Mock(return_value={})
        worker_errors = Mock()
        namespace = {
            "BackgroundStreamBridge": self.module.BackgroundStreamBridge,
            "os": SimpleNamespace(environ={}), "get_current_user_id": lambda: "owner", "get_settings": read_settings,
            "copy_current_request_context": copy_current_request_context, "has_request_context": has_request_context,
            "current_app": current_app, "g": g, "Response": Response, "stream_with_context": stream_with_context,
            "request": request, "json": json, "inspect": inspect, "nullcontext": nullcontext,
            "m365_action_card_events": lambda callback: nullcontext(), "complete_m365_request": Mock(),
            "pin_catalog_task": lambda task: task, "_release_chat_destination_lease": Mock(),
            "_extract_sse_event_payload": self.module._extract_sse_event_payload,
            "should_withhold_chat_event": should_withhold_chat_event, "public_chat_payload": lambda payload: payload,
            "_persist_retry_terminal_payload": Mock(return_value=False), "debug_print": worker_errors,
            "log_event": Mock(), "logging": logging, "M365ApprovalRequired": LookupError,
        }
        exec(compile(ast.Module(body=[builder], type_ignores=[]), str(source), "exec"), namespace)
        app = Flask(__name__)
        jobs = []
        app.extensions["executor"] = SimpleNamespace(submit=jobs.append)
        provisional = frame({"content": "provisional"})
        settings = {
            "chat_content_output_mode": "check_before_display",
            "enable_content_safety": True, "enable_content_safety_chat_output": True,
        }
        build = namespace["build_background_stream_response"]

        with app.test_request_context():
            response = build(lambda: iter([provisional]), content_check_settings=settings)
            jobs.pop()()
            delivered = response.get_data(as_text=True)
        self.assertEqual(delivered, "")
        read_settings.assert_not_called()

        with app.test_request_context():
            response = build(lambda: iter([provisional]))
            jobs.pop()()
            delivered = response.get_data(as_text=True)
        self.assertEqual(delivered, provisional)
        read_settings.assert_called_once_with()
        worker_errors.assert_not_called()

    def test_live_removal_replaces_cache_and_reconnect_history(self):
        self.session.publish(frame({"message_id": "answer", "content": "private-canary"}))
        self.session.publish(frame(self.replacement))
        replay = list(self.session.iter_events())
        self.assertEqual(len(replay), 1)
        self.assertIn("Reply removed.", replay[0])
        self.assertNotIn("private-canary", json.dumps(self.cache.events))
        self.assertNotIn(CHECK_METADATA, json.dumps(self.cache.metadata))
        self.assertFalse(self.session.is_active())

    def test_an_attached_bridge_discards_already_queued_provisional_chunks(self):
        bridge = self.module.BackgroundStreamBridge(stream_session=self.session)
        bridge.push(frame({"content": "private-canary"}))
        self.session.retract(self.replacement)
        delivered = list(bridge.iter_events())
        self.assertEqual(len(delivered), 1)
        self.assertNotIn("private-canary", "".join(delivered))
        self.assertIn("Reply removed.", delivered[0])

    def test_authoritative_removal_wins_even_when_an_old_cache_survives(self):
        self.session.publish(frame({"message_id": "answer", "content": "private-canary"}))
        self.session.publish(frame({"message_id": "answer", "done": True, "full_content": "private-canary"}))
        self.authoritative.return_value = strip_private_chat_checks(self.replacement)
        other_worker = self.module.ActiveConversationStreamSession("owner", "conversation")
        replay = list(other_worker.iter_events())
        self.assertNotIn("private-canary", "".join(replay))
        self.assertIn("Reply removed.", replay[0])
        self.authoritative.assert_called_with("conversation", "answer")

    def test_a_late_publisher_cannot_append_after_retraction(self):
        self.session.retract(self.replacement)
        accepted = self.session.publish(frame({"content": "private-canary"}))
        self.assertFalse(accepted)
        self.assertNotIn("private-canary", json.dumps(self.cache.events))

    def test_redis_content_publish_uses_one_write_and_records_a_shared_stop(self):
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        session.initialize()
        session.publish(frame({"content": "start"}))
        self.cache.publish_stream_content = Mock(side_effect=[1, "client_disconnect_timeout"])
        self.cache.can_publish_stream_content = Mock(return_value=True)
        self.cache.get_stream_session_meta = Mock(wraps=self.cache.get_stream_session_meta)
        self.cache.set_stream_session_meta = Mock(wraps=self.cache.set_stream_session_meta)
        self.cache.append_stream_session_event = Mock(wraps=self.cache.append_stream_session_event)

        accepted = session.publish(frame({"content": "persist immediately"}), allow_redis_fast_path=True)
        stopped = session.publish(frame({"content": "must not be published"}), allow_redis_fast_path=True)
        cancel_requested = session.is_cancel_requested(check_cache=False)

        self.assertTrue(accepted)
        self.assertFalse(stopped)
        self.assertTrue(cancel_requested)
        self.assertEqual(self.cache.publish_stream_content.call_count, 2)
        self.cache.append_stream_session_event.assert_not_called()
        self.cache.set_stream_session_meta.assert_not_called()
        self.cache.get_stream_session_meta.assert_not_called()

    def test_cosmos_stream_writes_only_attempt_metadata_until_pointer_renewal_is_due(self):
        self.cache.app_cache_is_using_redis = False
        clock = Mock(return_value=0)
        self.module.ActiveConversationStreamSession.__init__.__globals__["time"] = SimpleNamespace(monotonic=clock)
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        session.initialize()
        discovery_key = "owner:conversation"
        self.assertEqual(self.cache.metadata[discovery_key], {"submission_id": "turn"})
        self.cache.set_stream_session_meta = Mock(wraps=self.cache.set_stream_session_meta)
        self.cache.get_stream_session_meta = Mock(wraps=self.cache.get_stream_session_meta)
        self.cache.renew_cosmos_stream_discovery = Mock(wraps=self.cache.renew_cosmos_stream_discovery)

        expected = [frame({"content": str(index)}) for index in range(50)]
        for event in expected:
            session.publish(event)
        self.assertEqual(self.cache.events[session.cache_key], expected)
        self.assertEqual(self.cache.set_stream_session_meta.call_count, len(expected))
        self.assertTrue(all(call.args[0] == session.cache_key for call in self.cache.set_stream_session_meta.call_args_list))
        self.assertTrue(all(call.args[0] == session.cache_key for call in self.cache.get_stream_session_meta.call_args_list))
        self.cache.renew_cosmos_stream_discovery.assert_not_called()

        clock.return_value = 540
        session.note_keepalive()
        self.cache.renew_cosmos_stream_discovery.assert_called_once_with(discovery_key, "turn", 600)
        clock.return_value = 545
        session.publish(frame({"done": True}))
        self.assertEqual(self.cache.renew_cosmos_stream_discovery.call_count, 2)

    def test_cosmos_direct_deltas_commit_immediately_without_metadata_upserts(self):
        self.cache.app_cache_is_using_redis = False
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        session.initialize()
        first = frame({"content": "first"})
        session.publish(first, require_shared=True)
        self.cache.set_stream_session_meta = Mock(wraps=self.cache.set_stream_session_meta)
        self.cache.append_stream_session_event = Mock(wraps=self.cache.append_stream_session_event)

        for payload in ("second", "third"):
            event = frame({"content": payload})
            self.assertTrue(session.publish(event, require_shared=True))
            self.assertEqual(self.cache.events[session.cache_key][-1], event)
        self.assertEqual(self.cache.append_stream_session_event.call_count, 2)
        self.cache.set_stream_session_meta.assert_not_called()
        other_worker = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        status = other_worker.get_status_snapshot(shared_progress=True)
        self.assertEqual((status["event_count"], status["content_event_count"], status["content_chars"]), (3, 3, 16))

        session.publish(frame({"done": True}))
        session.close()
        status = other_worker.get_status_snapshot(shared_progress=True)
        self.assertEqual((status["event_count"], status["content_event_count"], status["content_chars"]), (4, 3, 16))
        self.assertEqual(status["status"], "completed")
        self.assertNotIn("replay_progress_finalized", status)

    def test_long_cosmos_direct_stream_renews_control_expiry_without_rewriting_metadata(self):
        self.cache.app_cache_is_using_redis = False
        clock = Mock(return_value=0)
        self.module.ActiveConversationStreamSession.__init__.__globals__["time"] = SimpleNamespace(monotonic=clock)
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        session.initialize()
        session.publish(frame({"content": "first"}), require_shared=True)
        self.cache.set_stream_session_meta = Mock(wraps=self.cache.set_stream_session_meta)
        self.cache.renew_cosmos_stream_metadata = Mock(return_value="renewed")
        self.cache.renew_cosmos_stream_discovery = Mock(return_value="renewed")

        clock.return_value = 59
        session.publish(frame({"content": "before renewal"}), require_shared=True)
        self.cache.renew_cosmos_stream_metadata.assert_not_called()
        clock.return_value = 60
        session.publish(frame({"content": "renew lease"}), require_shared=True)
        self.cache.renew_cosmos_stream_metadata.assert_called_once_with(session.cache_key, "turn", 600)
        self.cache.renew_cosmos_stream_discovery.assert_called_once_with("owner:conversation", "turn", 600)
        self.cache.set_stream_session_meta.assert_not_called()

        clock.return_value = 120
        self.cache.renew_cosmos_stream_metadata.return_value = "superseded"
        self.assertFalse(session.publish(frame({"content": "closed elsewhere"}), require_shared=True))
        self.assertNotIn("closed elsewhere", "".join(self.cache.events[session.cache_key]))

    def test_cosmos_stream_recovers_first_content_metadata_before_using_single_write_path(self):
        self.cache.app_cache_is_using_redis = False
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        session.initialize()
        write = self.cache.set_stream_session_meta

        def confirm_after_retry(key, metadata, **kwargs):
            write(key, metadata, **kwargs)
            return self.cache.set_stream_session_meta.call_count > 1

        self.cache.set_stream_session_meta = Mock(side_effect=confirm_after_retry)
        session.publish(frame({"content": "first"}), require_shared=True)
        session.publish(frame({"content": "recover shared state"}), require_shared=True)
        session.publish(frame({"content": "now optimized"}), require_shared=True)
        self.assertEqual(self.cache.set_stream_session_meta.call_count, 2)
        self.assertEqual(session.get_status_snapshot()["content_event_count"], 3)

    def test_missing_cosmos_progress_is_not_sealed_as_a_final_total(self):
        self.cache.app_cache_is_using_redis = False
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        session.initialize()
        session.publish(frame({"content": "first"}), require_shared=True)
        session.publish(frame({"content": "second"}), require_shared=True)
        get_progress = self.cache.get_cosmos_stream_progress
        self.cache.get_cosmos_stream_progress = Mock(return_value=None)

        with self.assertRaises(AzureError):
            session.get_status_snapshot(shared_progress=True)
        session.close()
        self.assertNotIn("replay_progress_finalized", self.cache.metadata[session.cache_key])
        self.cache.get_cosmos_stream_progress = get_progress
        self.assertEqual(session.get_status_snapshot(shared_progress=True)["content_event_count"], 2)

    def test_cosmos_direct_deltas_do_not_overwrite_stop_or_safety_state(self):
        self.cache.app_cache_is_using_redis = False
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        session.initialize()
        session.publish(frame({"content": "first"}), require_shared=True)
        session.publish(frame({"content": "second"}), require_shared=True)
        stopped = session.request_cancel()
        self.assertEqual(stopped["content_event_count"], 2)
        self.assertTrue(stopped["cancel_requested"])
        self.assertFalse(session.publish(frame({"content": "late after stop"}), require_shared=True))
        session.retract(self.replacement)
        self.assertEqual(list(session.iter_events()), [frame(strip_private_chat_checks(self.replacement))])
        self.assertFalse(session.publish(frame({"content": "late after safety"}), require_shared=True))

    def test_cosmos_registry_resolves_current_attempt_without_following_a_stale_local_alias(self):
        self.cache.app_cache_is_using_redis = False
        old = self.module.ActiveConversationStreamRegistry()
        new = self.module.ActiveConversationStreamRegistry(heartbeat_interval_seconds=7)
        old_session = old.start_session("owner", "conversation", submission_id="old", disconnect_grace_seconds=60)
        new.start_session("owner", "conversation", submission_id="new", disconnect_grace_seconds=60)
        self.cache.get_cosmos_stream_discovery = Mock(wraps=self.cache.get_cosmos_stream_discovery)

        explicit = old.get_session("owner", "conversation", active_only=True, submission_id="old")
        self.assertIs(explicit, old_session)
        self.cache.get_cosmos_stream_discovery.assert_not_called()
        latest = old.get_session("owner", "conversation", active_only=True)
        self.assertEqual(latest.submission_id, "new")
        self.assertEqual(latest.heartbeat_interval_seconds, 7)

        del self.cache.metadata["owner:conversation"]
        self.assertIsNone(old.get_session("owner", "conversation", active_only=True))

    def test_cosmos_initialization_failure_does_not_leave_a_live_session(self):
        self.cache.app_cache_is_using_redis = False
        self.cache.initialize_cosmos_stream_discovery = Mock(side_effect=StreamDiscoveryUnavailable("Unavailable"))
        registry = self.module.ActiveConversationStreamRegistry()

        with self.assertRaises(StreamDiscoveryUnavailable):
            registry.start_session("owner", "conversation", submission_id="turn", disconnect_grace_seconds=60)
        session = registry.get_session("owner", "conversation", active_only=True, submission_id="turn")
        self.assertIsNone(session)

    def test_cosmos_reattach_by_discovery_renews_before_accepting_even_when_timer_is_not_due(self):
        self.cache.app_cache_is_using_redis = False
        writer = self.module.ActiveConversationStreamRegistry()
        reader = self.module.ActiveConversationStreamRegistry()
        writer.start_session("owner", "conversation", submission_id="turn", disconnect_grace_seconds=60)
        session = reader.get_session("owner", "conversation", active_only=True)
        self.cache.renew_cosmos_stream_discovery = Mock(return_value="missing")

        with self.assertRaises(StreamDiscoveryUnavailable):
            session.mark_reattached(require_discovery=True)
        self.assertEqual(self.cache.metadata[session.cache_key]["reattach_count"], 0)
        self.cache.renew_cosmos_stream_discovery.return_value = "renewed"
        status = session.mark_reattached(require_discovery=True)
        self.assertEqual(status["reattach_count"], 1)
        self.assertEqual(self.cache.renew_cosmos_stream_discovery.call_count, 2)

    def test_cosmos_renewal_retries_transient_failure_without_waiting_a_full_interval(self):
        self.cache.app_cache_is_using_redis = False
        clock = Mock(return_value=0)
        self.module.ActiveConversationStreamSession.__init__.__globals__["time"] = SimpleNamespace(monotonic=clock)
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        session.initialize()
        self.cache.renew_cosmos_stream_discovery = Mock(side_effect=[StreamDiscoveryUnavailable("Temporary"), "renewed"])
        clock.return_value = 60
        session.publish(frame({"content": "first"}))
        clock.return_value = 61
        session.publish(frame({"content": "second"}))
        self.cache.renew_cosmos_stream_discovery.assert_called_once()
        clock.return_value = 65
        session.publish(frame({"content": "third"}))
        self.assertEqual(self.cache.renew_cosmos_stream_discovery.call_count, 2)

    def test_cosmos_discovery_read_failure_is_unconfirmed_in_chat_stream_routes(self):
        names = {"chat_stream_status_api", "chat_stream_cancel_api", "chat_stream_reattach_api"}
        source = APP / "route_backend_chats.py"
        nodes = [
            node for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(node, ast.FunctionDef) and node.name in names
        ]
        for node in nodes:
            node.decorator_list = []
        namespace = {
            "request": request, "jsonify": jsonify, "app_settings_cache": self.cache,
            "get_current_user_id": lambda: "owner", "_authorize_personal_conversation_access": lambda *_: {},
            "normalize_submission_id": lambda value: value, "SubmissionIdError": ValueError,
            "CosmosResourceNotFoundError": CosmosResourceNotFoundError, "AzureError": AzureError,
            "ChatRetryError": ValueError,
            "CHAT_STREAM_REGISTRY": Mock(**{"get_session.side_effect": StreamDiscoveryUnavailable("Unavailable")}),
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
        app = Flask(__name__)
        for name in sorted(names):
            with self.subTest(route=name), app.test_request_context(method="POST", json={}):
                response, status = namespace[name]("conversation")
                self.assertEqual(status, 503)
                self.assertEqual(response.get_json()["outcome"], "unconfirmed")

    def test_cosmos_registry_still_uses_legacy_metadata_when_no_submission_was_created(self):
        self.cache.app_cache_is_using_redis = False
        registry = self.module.ActiveConversationStreamRegistry()
        legacy = registry.start_session("owner", "legacy", disconnect_grace_seconds=60)
        self.cache.renew_cosmos_stream_discovery = Mock()
        legacy.publish(frame({"content": "legacy event"}))
        self.assertIs(registry.get_session("owner", "legacy", active_only=True), legacy)
        self.cache.renew_cosmos_stream_discovery.assert_not_called()

    def test_replaced_redis_submission_does_not_write_on_close(self):
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="old")
        session.initialize()
        session.publish(frame({"content": "start"}))
        self.cache.publish_stream_content = Mock(return_value=-2)
        self.cache.can_publish_stream_content = Mock(return_value=True)
        self.cache.set_stream_session_meta = Mock()
        self.cache.append_stream_session_event = Mock()

        accepted = session.publish(frame({"content": "stale"}), allow_redis_fast_path=True)
        session.close()

        self.assertFalse(accepted)
        self.cache.set_stream_session_meta.assert_not_called()
        self.cache.append_stream_session_event.assert_not_called()

    def test_unconfirmed_replay_terminates_live_and_reconnected_streams_without_an_append(self):
        session = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        session.initialize()
        provisional = frame({"content": "not a saved reply"})
        session.publish(provisional)
        self.cache.append_stream_session_event = Mock(side_effect=AssertionError("Replay is unavailable"))
        bridge = self.module.BackgroundStreamBridge(stream_session=session)
        bridge.push(provisional)
        payload = {
            "error": "Response replay could not be confirmed.", "error_code": "stream_replay_unconfirmed",
            "outcome": "unconfirmed", "done": True, "replace_content": True, "message_persisted": False,
        }
        terminal = frame(payload)
        self.assertTrue(session.publish(terminal))
        bridge.push(terminal)
        bridge.finish()
        session.close()
        other_worker = self.module.ActiveConversationStreamSession("owner", "conversation", submission_id="turn")
        self.assertEqual(list(bridge.iter_events()), [terminal])
        self.assertEqual(list(other_worker.iter_events()), [terminal])
        self.cache.append_stream_session_event.assert_not_called()

    def test_cancellation_is_correlated_once_and_not_logged_as_error(self):
        terminal = frame({"done": True, "cancelled": True, "message_id": "answer"})
        self.session.publish(terminal)
        self.session.publish(terminal)
        self.session.close()
        calls = self.module.log_chat_execution_outcome.call_args_list
        self.assertEqual(len(calls), 1)
        fields = calls[0].kwargs
        self.assertEqual(fields["execution_path"], "direct")
        self.assertEqual(fields["conversation_id"], "conversation")
        self.assertEqual(fields["status"], "cancelled")
        self.assertEqual(fields["outcome"], "cancelled")
        self.assertEqual(fields["failure"]["code"], "user_cancelled")
        terminal_logs = [
            call for call in self.module.log_event.call_args_list
            if call.args[0] == "[STREAMING] Stream session cancelled"
        ]
        self.assertTrue(terminal_logs)
        self.assertTrue(all(call.kwargs["level"] == logging.INFO for call in terminal_logs))

    def test_error_emits_failed_outcome_without_provider_diagnostics(self):
        self.session.publish(frame({"error": "PRIVATE_PROVIDER_MESSAGE"}))
        fields = self.module.log_chat_execution_outcome.call_args.kwargs
        self.assertEqual(fields["outcome"], "failed")
        self.assertEqual(fields["failure"], {"code": "stream_failed"})
        self.assertNotIn("PRIVATE_PROVIDER_MESSAGE", json.dumps(fields))

    def test_implicit_close_records_an_outcome_once(self):
        self.session.close()
        self.session.close()
        self.assertEqual(self.module.log_chat_execution_outcome.call_count, 1)

    def test_processing_note_polling_holds_pending_text_and_hides_retracted_text(self):
        source = APP / "functions_thoughts.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_visible_chat_thoughts")
        namespace = {"CosmosResourceNotFoundError": CosmosResourceNotFoundError}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        notes = [{
            "conversation_id": "conversation", "message_id": "answer",
            "content": "private-canary", "chat_content_checked_output": True,
            "chat_content_pending_hold": True,
        }]
        missing = Mock(side_effect=CosmosResourceNotFoundError(status_code=404))
        pending = namespace[function.name](notes, message_reader=missing)
        removed = namespace[function.name](notes, message_reader=lambda *_args: {
            "metadata": {"content_moderation": {"removed": True}},
        })
        allowed = namespace[function.name](notes, message_reader=lambda *_args: {
            "metadata": {"content_moderation": {"revision": "checked"}},
        })
        self.assertEqual(pending, [])
        self.assertEqual(removed, [])
        self.assertEqual(allowed, [{
            "conversation_id": "conversation", "message_id": "answer", "content": "private-canary",
        }])


class ChatCheckpointColdImportTests(unittest.TestCase):
    def test_real_leaf_modules_do_not_bootstrap_settings_or_network(self):
        for optimized in (False, True):
            for first, second in (
                ("functions_chat_content_checks", "functions_content_safety"),
                ("functions_content_safety", "functions_chat_content_checks"),
            ):
                with self.subTest(optimized=optimized, first=first):
                    script = f"""
import importlib, socket, sys
def blocked(*args, **kwargs):
    raise RuntimeError('Unexpected network access during checkpoint import.')
socket.create_connection = blocked
socket.socket.connect = blocked
importlib.import_module({first!r})
importlib.import_module({second!r})
from functions_chat_content_checks import check_chat_content
result = check_chat_content('ordinary', 'chat_output', user_id='owner', settings={{}})
if result.status != 'not_required' or 'config' in sys.modules or 'functions_settings' in sys.modules:
    raise RuntimeError('Disabled checkpoints initialized an application owner.')
"""
                    command = [sys.executable, *(["-O"] if optimized else []), "-c", script]
                    completed = subprocess.run(
                        command, env={**os.environ, "PYTHONPATH": str(APP)},
                        capture_output=True, text=True, timeout=30, check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
