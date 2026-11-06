# test_saved_analysis_cleanup_http.py
"""Real thought helper and deletion-route regressions with scoped SDK-shaped storage.

Version: 0.261.417
Implemented in: 0.261.417
Fresh normal/optimized processes block network and restore every injected callback.
"""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import patch
from flask import Blueprint, Flask
from test_support.offline_bootstrap import offline_app_imports
from test_support.orchestration_results import ResultContainer

def check(condition, message):
    if not condition:
        raise AssertionError(message)

def container(partition):
    value = ResultContainer()
    value.partition_field = partition
    return value

with offline_app_imports(), ExitStack() as stack:
    import functions_authentication as auth
    import functions_thoughts as thoughts
    import functions_workflow_result_store as result_store
    import route_backend_conversations as route

    messages = container("conversation_id")
    conversations = container("id")
    archived = container("conversation_id")
    notes = container("user_id")
    conversations.create_item({"id": "conversation", "user_id": "owner"})
    settings = {"enable_conversation_archiving": False}
    removed = []
    result_failed = [False]

    original_messages_query = messages.query_items
    def message_query(*args, **kwargs):
        rows = original_messages_query(*args, **kwargs)
        parameters = {p["name"]: p["value"] for p in kwargs.get("parameters", [])}
        return [row for row in rows if "@message_id" not in parameters or row["id"] == parameters["@message_id"]]

    original_notes_query = notes.query_items
    def notes_query(*args, **kwargs):
        rows = original_notes_query(*args, **kwargs)
        parameters = {p["name"]: p["value"] for p in kwargs.get("parameters", [])}
        return [row for row in rows if row.get("message_id") == parameters["@msg_id"]]

    def delete_result(user_id, conversation_id, message_id):
        if result_failed[0]:
            raise ConnectionError("Required result cleanup failed.")
        removed.append((user_id, conversation_id, message_id))

    for target, name, value in [
        (messages, "query_items", message_query), (notes, "query_items", notes_query),
        (thoughts, "cosmos_thoughts_container", notes),
        (result_store, "delete_chat_analysis_results", delete_result),
        (route, "get_settings", lambda: settings),
        (route, "cosmos_messages_container", messages),
        (route, "cosmos_conversations_container", conversations),
        (route, "cosmos_archived_messages_container", archived),
        (route, "_collect_child_message_documents", lambda *args: []),
        (route, "_rebuild_authorized_personal_conversation_used_documents", lambda *args: None),
        (route, "_invalidate_conversation_cache_after_message_mutation", lambda *args: None),
    ]:
        stack.enter_context(patch.object(target, name, value))
    app = Flask("analysis-cleanup-http")
    app.config.update(TESTING=True, SECRET_KEY="cleanup-http-test-secret")
    blueprint = Blueprint("cleanup_conversations", __name__)
    blueprint.before_request(auth.user_required_blueprint())
    route.register_route_backend_conversations(blueprint)
    app.register_blueprint(blueprint)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"oid": "owner", "roles": ["Admin"]}

    for archiving in (False, True):
        settings["enable_conversation_archiving"] = archiving
        for scenario in ("owned", "mirror", "workflow", "ordinary", "failed"):
            messages.items.clear()
            notes.items.clear()
            archived.items.clear()
            removed.clear()
            result_failed[0] = scenario == "failed"
            binding = {"kind": "chat", "user_id": "owner", "conversation_id": "conversation", "message_id": "assistant"}
            if scenario == "mirror":
                binding["message_id"] = "upstream-assistant"
            elif scenario == "workflow":
                binding = {"kind": "workflow", "workflow_id": "workflow", "run_id": "run", "task_id": "task"}
            metadata = {"user_info": {"user_id": "owner"}}
            if scenario != "ordinary":
                metadata.update(saved_analysis={"binding": binding}, source_thought_user_id="participant")
            messages.create_item({"id": "assistant", "conversation_id": "conversation", "role": "assistant", "metadata": metadata})
            for owner, message_id, identifier in [
                ("owner", "assistant", "owner-note"), ("participant", "assistant", "participant-note"),
                ("foreign", "assistant", "foreign-note"), ("owner", "another-message", "unrelated-note"),
            ]:
                notes.create_item({"id": identifier, "user_id": owner, "message_id": message_id})
            response = client.delete("/api/message/assistant", json={})
            check(response.status_code == (500 if scenario == "failed" else 200), f"{archiving}/{scenario}: {response.get_data(as_text=True)}")
            if scenario == "failed":
                check(("conversation", "assistant") in messages.items and not archived.items, "Failed cleanup must not delete/archive the message.")
                continue
            check(response.json["deleted_message_ids"] == ["assistant"], "The route must report the exact deleted message.")
            if scenario != "ordinary":
                check(("owner", "owner-note") not in notes.items and ("participant", "participant-note") not in notes.items, "The real two-argument helper must clean legitimate owner partitions.")
            else:
                check(("owner", "owner-note") in notes.items, "Ordinary messages must not invoke analysis cleanup.")
            check(("foreign", "foreign-note") in notes.items and ("owner", "unrelated-note") in notes.items, "Thought deletion must preserve foreign owners and other messages.")
            check(removed == ([("owner", "conversation", "assistant")] if scenario == "owned" else []), "Mirrored/workflow references must not delete upstream results.")
            if archiving:
                check(messages.read_item("assistant", "conversation")["metadata"]["is_deleted"], "Archived messages stay soft-deleted.")
                check(("conversation", "assistant") in archived.items, "Archiving must retain the masked message.")
            else:
                check(("conversation", "assistant") not in messages.items, "Permanent deletion must remove the message.")
    print("SAVED_ANALYSIS_CLEANUP_HTTP_OK")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_real_helper_and_delete_route_respect_partitions_and_cleanup_failure(optimized):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([
        str(ROOT / "application" / "single_app"), str(ROOT / "functional_tests"),
    ])
    result = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", PROBE],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SAVED_ANALYSIS_CLEANUP_HTTP_OK" in result.stdout
