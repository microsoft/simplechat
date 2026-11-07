#!/usr/bin/env python3
# test_workflow_handoff_status_route.py
"""
Functional test for following an accepted workflow hand-off's run through the status route V2 polls.
Version: 0.261.253
Implemented in: 0.261.295

V2's hand-off card follows the run an accept queued through 6b-2's run tracker, which reads 6b-1's
status route, ``GET /api/v2/orchestration/workflow-runs/status``. The card finds its run's row by the
accepted run's id, then checks the row's conversation, step and workflow. It never matches on
``orchestration_run_id``: a hand-off's run names the attempt that produced the hand-off, which isn't
always the run whose answer shows the card. This test accepts a hand-off through the real accept
route and reads the real status route, both through Flask's test client, and pins that:

- the status route lists the accepted run once, with exactly the row keys the tracker parses and no
  hand-off id, and with the run, workflow, conversation and step the card matches on;
- the hand-off list's queued item names that same run, so the card's match finds the row;
- when the answer is a later attempt that reused the hand-off step, the hand-off and its run are the
  same, and the row names the attempt that produced the hand-off, not the run the card is mounted on.

Refs #1549 and #1543. Checks use explicit raises, so they hold under ``python -O``.
"""

import importlib
from copy import deepcopy

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_handoff_planner import _require, _same
from test_orchestration_workflow_handoff_routes import (  # noqa: F401
    FIELD,
    STEP,
    accept,
    decision,
    expect,
    expected_run_id,
    hw,
    run,
    seed_handoff_run,
    status as handoff_list,
    stored_runs,
)
from test_orchestration_workflow_proposal_routes import CONVERSATION, RUN, SECOND, login
from test_support.versioning import assert_app_version_at_least
from test_workflow_chat_delivery_status_route import (
    ACTION_KEYS,
    DELIVERY_KEYS,
    ROW_KEYS,
    StrictQueryContainer,
    status_query_handler,
)


STATUS_URL = "/api/v2/orchestration/workflow-runs/status"
PAYLOAD_KEYS = {"available", "runs", "checked_at", "truncated"}


@pytest.fixture
def tracked(hw, monkeypatch):
    """``hw``, with 6b-1's status route reading what the accept route wrote.

    The route binds its reads through ``default_workflow_run_status_services``. Here the runs are the
    ones the accept route queued, behind a container that refuses any query but the status route's
    owner-scoped projection; the workflows are the store the accept route wrote; the run gate, the
    live runtime reader and the settings are the real ones.
    """
    delivery = importlib.import_module("functions_workflow_chat_delivery_status")
    context = importlib.import_module("functions_orchestration_workflow_context")
    containers = []

    def services():
        runs = StrictQueryContainer("runs", stored_runs(hw), query_handler=status_query_handler)
        containers.append(runs)
        return delivery.WorkflowRunStatusServices(
            runs=runs,
            workflows=hw.workflows,
            get_settings=lambda: deepcopy(hw.state.settings),
            settings_gate=context.workflow_run_settings_gate,
            live_status=hw.runtime.workflow_runtime_status,
            clock=lambda: hw.clock.now,
        )

    monkeypatch.setattr(delivery, "default_workflow_run_status_services", services)
    hw.status_containers = containers
    return hw


def status_rows(hw, conversation_id=CONVERSATION):
    """The status route's rows for one chat, read the way V2's tracker reads them."""
    response = hw.client.get(STATUS_URL, query_string={"conversation_id": conversation_id})
    payload = expect(response, 200)
    _same(set(payload), PAYLOAD_KEYS, "the status payload's keys")
    _same(payload["truncated"], False, "the status payload is complete")
    _require(hw.status_containers, "The status route did not read the runs this test stored.")
    _same(hw.status_containers[-1].refusals, [], "status queries the fake refused")
    return payload


def queued_item(hw, run_id):
    """The hand-off list's one item for ``run_id``, after checking it is the queued hand-off."""
    items = expect(handoff_list(hw, run_id), 200)["handoffs"]
    _same([item["handoff_id"] for item in items], [hw.handoff_id], "the hand-offs the run lists")
    item = items[0]
    _same(item["state"], "queued", "the hand-off's state")
    _same(item["actions"], [], "the queued hand-off's actions")
    _require(isinstance(item.get("run"), dict), f"The queued hand-off names no run: {item!r}")
    _require(isinstance(item.get("workflow"), dict), f"The queued hand-off names no workflow: {item!r}")
    return item


def card_finds(row, item, conversation_id):
    """Whether V2's ``workflowHandoffTrackedRun`` would show ``row`` as ``item``'s run."""
    return (
        bool(conversation_id) and bool(item["run"].get("id")) and bool(item["workflow"].get("id"))
        and row["run_id"] == item["run"]["id"] and row["conversation_id"] == conversation_id
        and row["step_id"] == item["step_id"] and row["workflow_id"] == item["workflow"]["id"]
    )


def require_queued_row(row, hw, run_id):
    _same(set(row), ROW_KEYS, "the status row's keys")
    _require("handoff_id" not in row, "The status row names the hand-off; the card matches on the run id.")
    _same(set(row["actions"]), ACTION_KEYS, "the status row's action keys")
    _same(set(row["delivery"]), DELIVERY_KEYS, "the status row's delivery keys")
    _same(row["run_id"], run_id, "the row's run")
    _same(row["workflow_id"], hw.workflow_id, "the row's workflow")
    _same(row["workflow_scope"], "personal", "the row's workflow scope")
    _same(row["conversation_id"], CONVERSATION, "the row's conversation")
    _same(row["step_id"], STEP, "the row's step")
    _same(row["status"], "queued", "the row's status")
    _same(row["waiting"], None, "the row's waiting reason")
    _same(row["error"], None, "the row's error")
    _same(row["actions"]["cancel"], True, "Cancel on the queued run")
    _same(row["actions"]["open_run"], True, "Open run on the queued run")
    _same(row["actions"]["approve"], False, "Approve on the queued run")
    _same(row["actions"]["retry"], False, "Retry on the queued run")


def test_version_includes_the_v2_workflow_handoff_card():
    assert_app_version_at_least("0.261.253")


def test_the_status_route_lists_the_accepted_hand_off_run_for_the_card(tracked):
    hw = tracked
    seed_handoff_run(hw)
    login(hw)
    _same(status_rows(hw)["runs"], [], "the status rows before the hand-off is accepted")

    accepted = expect(accept(hw), 201)
    run_id = expected_run_id(hw.workflow_id, hw.handoff_id)
    _same(accepted["run"]["id"], run_id, "the accepted run")
    _same(accepted["chat_delivery"], True, "the accepted run posts its result back to this chat")

    payload = status_rows(hw)
    _same(payload["available"], True, "chats can start workflows under the hand-off settings")
    _same(len(payload["runs"]), 1, "the status rows after accepting")
    row = payload["runs"][0]
    require_queued_row(row, hw, run_id)
    _same(row["orchestration_run_id"], RUN, "the row names the run that produced the hand-off")
    _same(row["live"], True, "the row was read from the run's live state")

    item = queued_item(hw, RUN)
    _same(item["run"]["id"], run_id, "the hand-off's run")
    _same(item["workflow"]["id"], hw.workflow_id, "the hand-off's workflow")
    _require(card_finds(row, item, CONVERSATION), "The card would not find the accepted run's status row.")
    _require(not card_finds(row, item, "conversation-2"), "The card would show another chat's row.")
    _require(not card_finds({**row, "step_id": "another-step"}, item, CONVERSATION),
             "The card would show another step's row.")
    _require(not card_finds({**row, "workflow_id": "another-workflow"}, item, CONVERSATION),
             "The card would show another workflow's row.")


def seed_later_attempt(hw):
    """A later attempt of the same turn that reused the completed hand-off step, as a retry stores it."""
    record = {key: value for key, value in deepcopy(run(hw)).items() if not key.startswith("_")}
    record.pop(FIELD, None)
    record.update({
        "id": SECOND, "run_id": SECOND, "attempt_root_run_id": RUN,
        "execution_steps": [{
            "step_id": STEP, "capability_id": "workflow_handoff", "status": "completed",
            "reused_from_run_id": RUN,
        }],
    })
    hw.runs.create_item(record)


def test_a_later_attempt_shows_the_run_its_producer_names(tracked):
    hw = tracked
    seed_handoff_run(hw)
    seed_later_attempt(hw)
    login(hw)
    listed = expect(handoff_list(hw, SECOND), 200)["handoffs"]
    _same([item["handoff_id"] for item in listed], [hw.handoff_id], "the hand-off the later attempt shows")
    _same(listed[0]["state"], "pending", "the hand-off's state on the later attempt")

    accepted = expect(accept(hw, run_id=SECOND), 201)
    run_id = expected_run_id(hw.workflow_id, hw.handoff_id)
    _same(accepted["run"]["id"], run_id, "the accepted run")
    _same(decision(hw, RUN)["state"], "queued", "the decision, stored on the producing run")
    _same(decision(hw, SECOND), None, "a decision on the later attempt")

    rows = status_rows(hw)["runs"]
    _same(len(rows), 1, "the status rows after accepting")
    row = rows[0]
    require_queued_row(row, hw, run_id)
    _same(row["orchestration_run_id"], RUN, "the row names the attempt that produced the hand-off")
    _require(row["orchestration_run_id"] != SECOND, "The row names the run the card is mounted on.")

    item = queued_item(hw, SECOND)
    _same(item["run"]["id"], run_id, "the hand-off's run on the later attempt")
    _require(card_finds(row, item, CONVERSATION),
             "The card on the later attempt would not find the run its producer started.")
    _same(queued_item(hw, RUN)["run"]["id"], run_id, "the hand-off's run on the producing attempt")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
