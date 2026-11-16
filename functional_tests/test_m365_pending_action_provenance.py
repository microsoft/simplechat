# test_m365_pending_action_provenance.py
"""Functional tests for verified orchestration provenance on pending-action cards.

Version: 0.261.325
Implemented in: 0.261.325

The real step bridge and pending-action capture use SDK-default Cosmos doubles.
Graph/model calls are mocked; no live outgoing action is performed.
"""

from copy import deepcopy
import importlib
from pathlib import Path
import sys

import pytest
from azure.cosmos._cosmos_responses import CosmosDict
from flask import g

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Existing isolated runtime fixtures configure real owners without Azure bootstrap.
from test_orchestration_operation_runtime import operations, send_call
from test_orchestration_m365_actions import USER, env, run_step, world
from test_support.m365 import CosmosContainer


def test_capture_step_reference_consumes_sdk_point_reads_and_real_owned_run(env, world, operations, monkeypatch):
    _journal, delivery, cards = operations
    point_reads, run_reads, captures = [], [], []
    run_store = CosmosContainer("conversation_id")
    saved_run = {**world.plan, "user_message_id": "sdk-user-message", "turn_id": "sdk-turn"}
    run_store.create_item(body=saved_run)
    config = sys.modules["config"]
    monkeypatch.setattr(config, "cosmos_orchestration_runs_container", run_store, raising=False)
    monkeypatch.setattr(config, "cosmos_orchestration_run_steps_container", CosmosContainer("run_id"), raising=False)
    monkeypatch.delitem(sys.modules, "functions_orchestration_runs")
    runs = importlib.import_module("functions_orchestration_runs")
    assert runs.get_orchestration_run.__module__ == "functions_orchestration_runs"
    original_run_read = run_store.read_item
    original_request_read = world.jobs.read_item
    original_capture = delivery._dependencies["capture_step_reference"]

    def read_run(item, partition_key):
        result = original_run_read(item, partition_key)
        run_reads.append((item, partition_key, result))
        return result

    def read_request(item, partition_key):
        result = original_request_read(item, partition_key)
        point_reads.append((item, partition_key, result))
        return result

    def capture(context, action_id):
        before = len(point_reads)
        result = original_capture(context, action_id)
        captures.append((context, result, point_reads[before:]))
        return result

    monkeypatch.setattr(run_store, "read_item", read_run)
    monkeypatch.setattr(world.jobs, "read_item", read_request)
    monkeypatch.setitem(delivery._dependencies, "capture_step_reference", capture)
    world.graph_response = (200, {"id": "draft-1", "changeKey": "draft-v1"})
    world.replies = [send_call()]
    run_step(env, world, execution_intent="operate", journal=world.journal())
    assert captures
    for context, reference, reads in captures:
        assert len(reads) == 1
        item, partition, record = reads[0]
        assert isinstance(record, CosmosDict) and partition == USER and item == context.request_id
        assert record["actor_user_id"] == USER and record["conversation_id"] == context.conversation_id
        assert reference["run_id"] == record["orchestration"]["run_id"] == "run-2"
        assert reference["step_id"] == record["orchestration"]["step_id"]
        assert reference["provenance_version"] == 1
        assert reference["user_message_id"] == "sdk-user-message" and reference["turn_id"] == "sdk-turn"
    assert run_reads and all(isinstance(row[2], CosmosDict) for row in run_reads)
    assert all(row[:2] == ("run-2", context.conversation_id) for row in run_reads)
    action = next(iter(world.pending.items.values()))
    assert action["review_provenance_version"] == 1 and action["m365_execution"]["step_ref"] == reference
    projected = cards.sanitize_msgraph_pending_action_for_client(action, viewer_user_id=USER)
    assert projected["producing_user_message_id"] == "sdk-user-message"
    assert projected["turn_id"] == "sdk-turn" and projected["orchestration_run_id"] == "run-2"
    request_key = (USER, context.request_id)
    run_key = (context.conversation_id, "run-2")
    original_record = deepcopy(world.jobs.items[request_key])
    original_run = deepcopy(run_store.items[run_key])
    with world.app.test_request_context("/api/test/provenance"):
        setattr(g, env.runtime.M365_STEP_SELECTION_KEY, deepcopy(reference["selection"]))
        for target, changes in (
            ("request", {"actor_user_id": "another-owner"}),
            ("request", {"conversation_id": "another-conversation"}),
            ("run", {"user_id": "another-owner"}),
            ("run", {"status": "cancelled"}),
        ):
            world.jobs.items[request_key] = deepcopy(original_record)
            run_store.items[run_key] = deepcopy(original_run)
            record = world.jobs.items[request_key] if target == "request" else run_store.items[run_key]
            record.update(changes)
            with pytest.raises(env.approvals.M365PolicyError):
                original_capture(context, action["m365_execution"]["action_id"])


def test_producing_message_identity_is_captured_from_the_verified_owned_run(env, world, operations, monkeypatch):
    _journal, delivery, cards = operations
    world.plan.update(user_message_id="saved-user-message", turn_id="saved-turn")
    world.graph_response = (200, {"id": "draft-1", "changeKey": "draft-v1"})
    world.replies = [send_call()]
    run_step(env, world, execution_intent="operate", journal=world.journal())
    action = next(iter(world.pending.items.values()))
    step = action["m365_execution"]["step_ref"]
    assert action["review_provenance_version"] == 1
    assert step["user_message_id"] == "saved-user-message"
    assert step["turn_id"] == "saved-turn" and step["provenance_version"] == 1
    owner = cards.sanitize_msgraph_pending_action_for_client(action, viewer_user_id=USER)
    assert owner["producing_user_message_id"] == "saved-user-message"
    assert owner["orchestration_run_id"] == "run-2" and owner["turn_id"] == "saved-turn"

    monkeypatch.setitem(delivery._dependencies, "view_authorizer", lambda saved, viewer: viewer == "authorized-shared-viewer")
    shared = cards.sanitize_msgraph_pending_action_for_client(action, viewer_user_id="authorized-shared-viewer")
    denied = cards.sanitize_msgraph_pending_action_for_client(action, viewer_user_id="unrelated")
    anonymous = cards.sanitize_msgraph_pending_action_for_client(action)
    assert shared["producing_user_message_id"] == owner["producing_user_message_id"]
    assert denied["producing_user_message_id"] == anonymous["producing_user_message_id"] == ""
    assert denied["orchestration_run_id"] == denied["turn_id"] == ""

    altered = deepcopy(action)
    altered["m365_execution"]["step_ref"]["user_message_id"] = "unverified-message"
    invalid = cards.sanitize_msgraph_pending_action_for_client(altered, viewer_user_id=USER)
    assert invalid["producing_user_message_id"] == invalid["orchestration_run_id"] == invalid["turn_id"] == ""

    mismatched = deepcopy(action)
    mismatched["m365_execution"]["step_ref"]["conversation_id"] = "another-conversation"
    mismatched["material_fingerprint"] = delivery.pending_delivery_fingerprint(mismatched)
    invalid = cards.sanitize_msgraph_pending_action_for_client(mismatched, viewer_user_id=USER)
    assert invalid["producing_user_message_id"] == ""

    historical = deepcopy(action)
    historical.pop("review_provenance_version")
    historical["material_fingerprint"] = delivery.pending_delivery_fingerprint(historical)
    untouched = deepcopy(historical)
    invalid = cards.sanitize_msgraph_pending_action_for_client(historical, viewer_user_id=USER)
    assert invalid["producing_user_message_id"] == invalid["orchestration_run_id"] == invalid["turn_id"] == ""
    assert historical == untouched

    delayed = deepcopy(action)
    delayed.update(action_mode="delayed")
    delayed["material_fingerprint"] = delivery.pending_delivery_fingerprint(delayed)
    invalid = cards.sanitize_msgraph_pending_action_for_client(delayed, viewer_user_id=USER)
    assert invalid["producing_user_message_id"] == ""


def test_historical_missing_producing_identity_is_not_guessed_or_migrated(env, world, operations):
    _journal, _delivery, cards = operations
    world.graph_response = (200, {"id": "draft-1", "changeKey": "draft-v1"})
    world.replies = [send_call()]
    run_step(env, world, execution_intent="operate", journal=world.journal())
    action = next(iter(world.pending.items.values()))
    projected = cards.sanitize_msgraph_pending_action_for_client(action, viewer_user_id=USER)
    assert "provenance_version" not in action["m365_execution"]["step_ref"]
    assert projected["producing_user_message_id"] == projected["orchestration_run_id"] == projected["turn_id"] == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
