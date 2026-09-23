# test_chat_content_streaming.py
"""
Functional regressions for content-check streaming and processing-note visibility.
Version: 0.261.127
Implemented in: 0.261.127

Execute the shipped stream session/bridge classes against an isolated cache.
Cold-import probes use real modules with network access blocked.
"""

import ast
from copy import deepcopy
from datetime import datetime
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

from azure.cosmos.exceptions import CosmosResourceNotFoundError


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from functions_chat_content_checks import CHECK_METADATA, strip_private_chat_checks


class Cache:
    def __init__(self):
        self.metadata = {}
        self.events = {}

    def initialize_stream_session_cache(self, key, metadata, **kwargs):
        self.metadata[key] = deepcopy(metadata)
        self.events[key] = []

    def set_stream_session_meta(self, key, metadata, **kwargs):
        self.metadata[key] = deepcopy(metadata)

    def get_stream_session_meta(self, key):
        return deepcopy(self.metadata.get(key))

    def append_stream_session_event(self, key, event, **kwargs):
        self.events.setdefault(key, []).append(event)

    def get_stream_session_events(self, key, start_index=0):
        return list(self.events.get(key, [])[start_index:])


def stream_classes(cache, authoritative):
    source = APP / "route_backend_chats.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {
        "BackgroundStreamBridge", "ActiveConversationStreamSession",
        "_safe_int", "_utcnow_iso", "_parse_iso_datetime", "_truncate_log_text",
        "_build_stream_status_payload", "_extract_sse_event_payload",
    }
    definitions = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            definitions.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and (
                target.id.startswith("STREAM_STATUS_") or target.id == "TERMINAL_STREAM_STATUSES"
            ) for target in node.targets
        ):
            definitions.append(node)
    namespace = {
        "queue": queue, "threading": threading, "time": time, "json": json,
        "logging": logging, "datetime": datetime, "app_settings_cache": cache,
        "log_event": Mock(), "strip_private_chat_checks": strip_private_chat_checks,
        "retracted_stream_payload": authoritative,
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
