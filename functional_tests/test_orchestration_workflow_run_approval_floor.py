#!/usr/bin/env python3
# test_orchestration_workflow_run_approval_floor.py
"""
Functional test for the manual approval floor on plans that start a saved workflow.
Version: 0.261.212
Implemented in: 0.261.212

This test ensures that a plan with an enabled workflow_run step always waits for the user to run
it. normalize_plan saves such a plan as manual with an approval floor, whatever approval mode was
asked for: by the request, by the admin default, auto or timed. It does so on every path that
produces a plan: the first plan, a regenerated or replanned turn, answered questions, plan-editor
revisions and their other outcomes, and checked plan edits. apply_plan_edits never lifts it.

claim_plan_run refuses a saved plan whose run record or plan no longer reads manual, so a changed
record cannot start a workflow, while a plan whose run steps were switched off is not held back.
The approval card names each workflow the plan starts by its name and trigger, with no record id,
and says when it is paused. A plan that starts no workflow keeps the mode it asked for.
"""

import importlib
import json
import uuid
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_orchestration_workflow_run_capability import (  # noqa: F401
    ANSWER,
    HOSTILE_NAME,
    MESSAGE,
    RUN_ONLY,
    WORKFLOW_RUN,
    _handle,
    _plan_request,
    _raw_plan,
    _record,
    _run,
    _step,
    planning,
    registry,
    schema,
)
from test_orchestration_workflow_run_planning_context import (  # noqa: F401
    DIGEST_ID,
    DIGEST_REQUEST,
    OWNER,
    RUN_SETTINGS,
    RUNS,
    _build,
    _frames,
    _readers,
    wf,
)
from test_orchestration_workflow_setting_off_golden import IDENTITY
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least


FLOOR = {"mode": "manual", "reason": WORKFLOW_RUN}
CONVERSATION = "conversation-1"
NOTES = {
    "step_id": "notes", "capability_id": "compose",
    "arguments": {"instruction": "Note what changed this week.", "knowledge_basis": "general_knowledge"},
    "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}],
}
ANSWERED = [{
    "question": "Which workflow should run?", "answer": {"workflow": "Weekly digest"}, "action": "accept",
}]
TURN_CONTEXT = {
    "turn_id": "turn-1", "planner_contract_version": 2, "user_message": MESSAGE,
    "user_message_id": "message-1", "user_message_fingerprint": "message-fingerprint",
    "resolved_message": MESSAGE, "seeds": {}, "original_seeds": {},
    "answered_questions": [], "planning_token_usage": {},
}


def _plan(schema, planning, steps, final="answer", *, approval_mode=None, settings=RUN_ONLY):
    return schema.normalize_plan(
        _raw_plan(steps, final), CONVERSATION, OWNER, settings=deepcopy(settings),
        approval_mode=approval_mode, contract_version=2, turn_id=TURN_CONTEXT["turn_id"],
        available_capability_ids=["compose", "web_search", WORKFLOW_RUN], workflow_planning=planning,
    )


def _assert_waits_for_the_user(plan):
    approval = plan["approval"]
    assert (approval["mode"], approval["state"], plan["status"]) == ("manual", "pending", "awaiting_approval")
    assert approval["floor"] == FLOOR
    assert approval["approved_at"] is None and approval["approved_by"] is None


def _entry(planning, name):
    return next(entry for entry in planning["catalog"]["workflows"] if entry["name"] == name)


def _record_ids(planning):
    return [record["id"] for record in planning["handles"]["workflows"].values()]


def test_version_includes_the_approval_floor():
    assert_app_version_at_least("0.261.212")


# ---------------------------------------------------------------------------
# The floor is a descriptor field
# ---------------------------------------------------------------------------

def test_only_starting_a_saved_workflow_sets_an_approval_floor(registry):
    floors = registry.approval_floor_capability_ids()
    assert floors == frozenset({WORKFLOW_RUN})
    for descriptor in registry.CAPABILITY_REGISTRY:
        expected = registry.APPROVAL_FLOOR_MANUAL if descriptor["id"] == WORKFLOW_RUN else None
        assert descriptor.get("approval_floor") == expected, descriptor["id"]
    assert registry.get_capability(WORKFLOW_RUN)["approval_floor"] == "manual"


# ---------------------------------------------------------------------------
# normalize_plan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("approval_mode", "admin_default"), [
    (None, None), ("manual", None), ("auto", None), ("timed", None), ("AUTO", None),
    (None, "auto"), (None, "timed"), ("auto", "auto"), ("timed", "timed"), ("unknown", "auto"),
])
def test_a_plan_that_starts_a_workflow_always_waits_for_the_user(schema, planning, approval_mode, admin_default):
    settings = {**RUN_ONLY}
    if admin_default is not None:
        settings["chat_orchestration_default_approval_mode"] = admin_default
    digest = _handle(planning, "Weekly digest")
    with_answer = _plan(schema, planning, [ANSWER, _run(digest)], approval_mode=approval_mode, settings=settings)
    run_only = _plan(schema, planning, [_run(digest)], final=None, approval_mode=approval_mode, settings=settings)
    _assert_waits_for_the_user(with_answer)
    _assert_waits_for_the_user(run_only)


@pytest.mark.parametrize(("approval_mode", "status", "state"), [
    ("auto", "approved", "approved"), ("timed", "awaiting_approval", "pending"),
    ("manual", "awaiting_approval", "pending"),
])
def test_a_plan_that_starts_no_workflow_keeps_the_mode_it_asked_for(schema, planning, approval_mode, status, state):
    plan = _plan(schema, planning, [ANSWER], approval_mode=approval_mode)
    floor = schema.plan_approval_floor(plan)
    assert (plan["approval"]["mode"], plan["approval"]["state"], plan["status"]) == (approval_mode, state, status)
    assert "floor" not in plan["approval"] and floor is None
    assert "workflows" not in plan["inputs"]


def test_only_an_enabled_run_step_sets_the_floor(schema, planning):
    plan = _plan(schema, planning, [ANSWER, _run(_handle(planning, "Weekly digest"))], approval_mode="auto")
    enabled = schema.plan_approval_floor(plan)
    _step(plan, "run_digest")["enabled"] = False
    disabled = schema.plan_approval_floor(plan)
    malformed = [
        schema.plan_approval_floor(value)
        for value in (None, {}, {"steps": None}, {"steps": ["not a step", {"capability_id": WORKFLOW_RUN, "enabled": False}]})
    ]
    assert enabled == FLOOR
    assert disabled is None
    assert malformed == [None, None, None, None]


def test_the_approval_card_names_each_workflow_the_plan_starts(schema, planning):
    digest = _entry(planning, "Weekly digest")
    other = next(
        entry for entry in planning["catalog"]["workflows"]
        if entry["durable"] is True and entry["enabled"] is True
    )
    plan = _plan(schema, planning, [ANSWER, _run(other["handle"], step_id="run_other"), _run(digest["handle"])])
    workflows = plan["inputs"]["workflows"]
    assert workflows == [
        {
            "handle": other["handle"], "name": other["name"],
            "trigger_summary": other["trigger_summary"], "paused": False,
        },
        {
            "handle": digest["handle"], "name": "Weekly digest",
            "trigger_summary": digest["trigger_summary"], "paused": True,
        },
    ]
    assert digest["trigger_summary"]
    # Handles and names only: the record ids stay in the server-side handle map.
    text = json.dumps(plan)
    for record_id in _record_ids(planning):
        assert record_id not in text
    assert DIGEST_ID not in text


def test_a_hostile_workflow_name_reaches_the_card_as_bounded_text(schema, wf):
    hostile = {
        "id": DIGEST_ID, "name": HOSTILE_NAME + " " + "x" * 400, "trigger_type": "manual",
        "is_enabled": True, "durable_execution": True, "updated_at": "2026-09-01T00:00:00+00:00",
    }
    planning = _build(wf, [], RUN_SETTINGS, request_text="Run it now.", workflows=lambda user_id: [hostile])
    plan = _plan(schema, planning, [ANSWER, _run(planning["catalog"]["workflows"][0]["handle"])])
    [workflow] = plan["inputs"]["workflows"]
    # The server keeps the name as text; the browser renders it as text.
    assert workflow["name"].startswith(HOSTILE_NAME)
    assert len(workflow["name"]) <= 200 and workflow["paused"] is False


def test_plan_edits_narrow_but_never_lift_the_floor(schema, planning):
    digest, other = _handle(planning, "Weekly digest"), _durable_enabled_handle(planning)
    plan = _plan(
        schema, planning, [ANSWER, NOTES, _run(digest), _run(other, step_id="run_other")], approval_mode="auto",
    )
    _assert_waits_for_the_user(plan)

    edited = schema.apply_plan_edits(deepcopy(plan), {
        "disabled_step_ids": ["notes", "run_other"],
        # Edits have no approval fields; anything like them is ignored.
        "approval": {"mode": "auto"}, "approval_mode": "auto",
    }, contract_version=2)
    floor = schema.plan_approval_floor(edited)
    assert edited["approval"]["mode"] == "manual" and edited["approval"]["floor"] == FLOOR
    assert floor == FLOOR

    # With every run step off, nothing starts a workflow; the plan still waits as it was saved.
    stopped = schema.apply_plan_edits(deepcopy(plan), {"disabled_step_ids": ["run_digest", "run_other"]}, contract_version=2)
    assert schema.plan_approval_floor(stopped) is None
    assert stopped["approval"]["mode"] == "manual"


def _durable_enabled_handle(planning):
    return next(
        entry["handle"] for entry in planning["catalog"]["workflows"]
        if entry["durable"] is True and entry["enabled"] is True
    )


# ---------------------------------------------------------------------------
# Every planning path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("options", [
    {"approval_mode": "auto"},
    {"approval_mode": "timed"},
    {"approval_mode": None, "settings": {**RUN_ONLY, "chat_orchestration_default_approval_mode": "auto"}},
    {"approval_mode": "auto", "replan_hint": "Regenerate the plan with a shorter answer."},
    {"approval_mode": "timed", "answered_questions": ANSWERED},
], ids=["auto", "timed", "admin_default_auto", "regenerate_or_replan", "answered_questions"])
def test_every_planned_turn_that_starts_a_workflow_waits_for_the_user(monkeypatch, planning, options):
    record = _record()
    reply = _raw_plan([ANSWER, _run(_handle(planning, "Weekly digest"))])
    kind, plan = _plan_request(monkeypatch, planning, [reply], record, **options)
    assert kind == "plan" and len(record.calls) == 1
    _assert_waits_for_the_user(plan)
    assert [workflow["name"] for workflow in plan["inputs"]["workflows"]] == ["Weekly digest"]


def test_a_dropped_run_step_leaves_the_rest_of_the_plan_in_its_own_mode(monkeypatch, planning):
    reply = _raw_plan([ANSWER, _run(_handle(planning, "Contract watcher"))])
    record = _record()
    kind, plan = _plan_request(monkeypatch, planning, [reply, reply], record, approval_mode="auto")
    assert kind == "plan" and [step["capability_id"] for step in plan["steps"]] == ["compose"]
    assert plan["approval"]["mode"] == "auto" and plan["status"] == "approved"
    assert "floor" not in plan["approval"]


def test_a_revised_plan_that_starts_a_workflow_records_its_floor(monkeypatch, planning):
    reply = dict(_raw_plan([ANSWER, _run(_handle(planning, "Weekly digest"))]), revised_request="Also run my weekly digest.")
    record = _record()
    kind, plan = _plan_request(
        monkeypatch, planning, [reply], record, approval_mode="manual",
        edit_context={"instruction": "Run my weekly digest too.", "current_plan": {}},
    )
    assert kind == "plan"
    _assert_waits_for_the_user(plan)


def test_a_checked_plan_edit_that_starts_a_workflow_waits_for_the_user(modules, monkeypatch, schema, planning):
    editing = importlib.import_module("functions_orchestration_plan_editing")
    monkeypatch.setattr(editing, "resolve_agent_catalog", lambda *args, **kwargs: [])
    monkeypatch.setattr(editing, "resolve_action_catalog", lambda *args, **kwargs: [])
    plan = _plan(schema, planning, [ANSWER, _run(_handle(planning, "Weekly digest"))], approval_mode="auto")
    # A restored version could carry any saved approval; the check decides it again.
    plan["approval"] = {**plan["approval"], "mode": "auto", "state": "approved"}
    plan["approval"].pop("floor")
    context = {
        "conversation_id": CONVERSATION, "turn_id": "turn-1", "user_message": MESSAGE,
        "resolved_message": MESSAGE, "seeds": {}, "planner_contract_version": 2,
        "workflow_planning": planning,
    }
    checked = editing.validate_edited_plan(plan, context, OWNER, deepcopy(RUN_ONLY), deepcopy(IDENTITY))
    _assert_waits_for_the_user(checked)
    assert [workflow["name"] for workflow in checked["inputs"]["workflows"]] == ["Weekly digest"]


# ---------------------------------------------------------------------------
# Saved plans: revisions, the claim backstop
# ---------------------------------------------------------------------------

@pytest.fixture
def store(modules, monkeypatch):
    runs = AtomicMemoryContainer("conversation_id")
    steps = AtomicMemoryContainer("run_id")
    run_store = importlib.import_module("functions_orchestration_runs")
    config = importlib.import_module("config")
    for module in (config, run_store):
        monkeypatch.setattr(module, "cosmos_orchestration_runs_container", runs)
        monkeypatch.setattr(module, "cosmos_orchestration_run_steps_container", steps)
    return SimpleNamespace(
        runs=runs, run_store=run_store,
        revisions=importlib.import_module("functions_orchestration_plan_revisions"),
    )


def _saved(store, plan, planning):
    return store.run_store.create_orchestration_run(
        deepcopy(plan), OWNER, CONVERSATION, turn_index=1,
        turn_context={**deepcopy(TURN_CONTEXT), "workflow_planning": deepcopy(planning)}, idempotent=True,
    )


def _claim(store, record, **kwargs):
    return store.revisions.claim_plan_run(
        record["id"], OWNER, CONVERSATION, expected_version=record.get("edit_version"),
        settings=deepcopy(RUN_ONLY), **kwargs,
    )


def _revision_request(record):
    return {
        "conversation_id": CONVERSATION, "expected_version": record["edit_version"],
        "submission_id": str(uuid.uuid4()), "action": "ask", "instruction": "Keep the digest.",
    }


def test_a_saved_floor_plan_is_manual_in_the_run_record_and_runs_when_claimed(store, schema, planning):
    plan = _plan(schema, planning, [ANSWER, _run(_handle(planning, "Weekly digest"))], approval_mode="auto")
    record = _saved(store, plan, planning)
    assert record["approval"]["mode"] == "manual" and record["status"] == "awaiting_approval"
    assert record["plan"]["approval"]["floor"] == FLOOR
    claimed = _claim(store, record)
    assert claimed["status"] == "running" and claimed["started_at"]
    assert claimed["approval"]["state"] == "approved" and claimed["approval"]["floor"] == FLOOR


def test_every_plan_editor_outcome_keeps_the_floor(store, schema, planning):
    digest = _handle(planning, "Weekly digest")
    plan = _plan(schema, planning, [ANSWER, _run(digest)], approval_mode="auto")
    record = _saved(store, plan, planning)

    held = store.revisions.begin_plan_edit(record["id"], OWNER, CONVERSATION, plan_id=plan["plan_id"])
    assert held["approval"] == held["plan"]["approval"]
    _assert_waits_for_the_user(held["plan"])

    # The same plan with no new version: a message, a question or a discard.
    claim = store.revisions.claim_plan_revision(held["id"], OWNER, CONVERSATION, _revision_request(held))
    answered = store.revisions.complete_plan_revision(claim, kind="message")
    assert answered["approval"] == answered["plan"]["approval"]
    _assert_waits_for_the_user(answered["plan"])

    # A new version from the editor's planner, which plans in manual mode.
    revised = _plan(schema, planning, [ANSWER, _run(digest)], approval_mode="manual")
    claim = store.revisions.claim_plan_revision(answered["id"], OWNER, CONVERSATION, _revision_request(answered))
    published = store.revisions.complete_plan_revision(claim, kind="plan", document=revised)
    assert published["id"] != record["id"] and published["approval"] == published["plan"]["approval"]
    _assert_waits_for_the_user(published["plan"])

    claimed = _claim(store, published)
    assert claimed["status"] == "running" and claimed["approval"]["floor"] == FLOOR


def _set_mode(target, mode):
    target["approval"] = {**target["approval"], "mode": mode}


@pytest.mark.parametrize("change", [
    "record_auto", "record_timed", "plan_auto", "plan_timed", "both_auto",
    "record_missing", "plan_missing", "record_not_a_dict",
])
def test_a_saved_floor_plan_that_no_longer_reads_manual_cannot_start(store, schema, planning, change):
    plan = _plan(schema, planning, [ANSWER, _run(_handle(planning, "Weekly digest"))], approval_mode="auto")
    record = _saved(store, plan, planning)
    changed = store.runs.read_item(record["id"], CONVERSATION)
    if change in ("record_auto", "both_auto"):
        _set_mode(changed, "auto")
    if change == "record_timed":
        _set_mode(changed, "timed")
    if change in ("plan_auto", "both_auto"):
        _set_mode(changed["plan"], "auto")
    if change == "plan_timed":
        _set_mode(changed["plan"], "timed")
    if change == "record_missing":
        changed.pop("approval")
    if change == "plan_missing":
        changed["plan"].pop("approval")
    if change == "record_not_a_dict":
        changed["approval"] = "manual"
    store.runs.upsert_item(changed)

    with pytest.raises(store.revisions.PlanRevisionError) as caught:
        _claim(store, changed)
    saved = store.runs.read_item(record["id"], CONVERSATION)
    assert (caught.value.code, caught.value.status_code) == ("approval_floor_required", 409)
    # Fixed text only: nothing about the plan or the workflow.
    assert "Weekly digest" not in caught.value.message and DIGEST_ID not in caught.value.message
    assert saved["status"] == "awaiting_approval" and saved["started_at"] is None
    assert "execution_lease" not in saved


def test_a_changed_plan_whose_run_steps_are_switched_off_is_not_held_back(store, schema, planning):
    plan = _plan(schema, planning, [ANSWER, _run(_handle(planning, "Weekly digest"))], approval_mode="auto")
    record = _saved(store, plan, planning)
    changed = store.runs.read_item(record["id"], CONVERSATION)
    _set_mode(changed, "auto")
    store.runs.upsert_item(changed)
    claimed = _claim(store, changed, edits={"disabled_step_ids": ["run_digest"]})
    assert claimed["status"] == "running"
    assert _step(claimed["plan"], "run_digest")["enabled"] is False


# ---------------------------------------------------------------------------
# Real HTTP: /plan in auto mode, and /run with a changed record
# ---------------------------------------------------------------------------

def _record_workflow_starts(monkeypatch, schema):
    executor = importlib.import_module("functions_orchestration_executor")
    original = executor._dependency_adapter
    started = []

    def adapter(capability_id):
        if capability_id != WORKFLOW_RUN:
            return original(capability_id)

        def start(step, context, **kwargs):
            started.append(step["step_id"])
            return schema.build_step_result(summary="Started.")
        return start

    monkeypatch.setattr(executor, "_dependency_adapter", adapter)
    return started


def test_real_http_an_auto_plan_that_starts_a_workflow_waits_and_a_changed_record_cannot_run(
    real_http_harness, wf, schema, monkeypatch,
):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings.update(enable_user_workspace=False, allow_user_workflows=True, **{RUNS: True})
    for name, reader in _readers([]).items():
        monkeypatch.setitem(wf._DEFAULT_READERS, name, reader)
    started = _record_workflow_starts(monkeypatch, schema)
    digest = _handle(_build(wf, [], RUN_SETTINGS, request_text=DIGEST_REQUEST), "Weekly digest")
    harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": DIGEST_REQUEST,
            "message_ids": [], "requires_retrieval": False, "clarification": "",
        }),
        json.dumps({"kind": "plan", "steps": [compose_step(), _run(digest)], "final_response": input_binding("prepare")}),
        "The complete note.",
    ]
    planned = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": CONVERSATION, "turn_id": "floor-turn", "message": DIGEST_REQUEST,
        "approval_mode": "auto", "planner_contract_version": 1,
    }, buffered=True)
    frames = _frames(planned)
    assert planned.status_code == 200 and "plan" in frames[-1], frames
    plan = frames[-1]["plan"]
    _assert_waits_for_the_user(plan)
    assert [workflow["name"] for workflow in plan["inputs"]["workflows"]] == ["Weekly digest"]
    assert DIGEST_ID not in planned.get_data(as_text=True)
    record = harness.runs.read_item(plan["run_id"], CONVERSATION)
    assert record["approval"]["mode"] == "manual" and record["plan"] == plan

    changed = deepcopy(record)
    _set_mode(changed, "auto")
    _set_mode(changed["plan"], "auto")
    harness.runs.upsert_item(changed)
    blocked = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": CONVERSATION, "run_id": record["id"],
    }, buffered=True)
    saved = harness.runs.read_item(record["id"], CONVERSATION)
    assert blocked.status_code == 409 and blocked.get_json()["code"] == "approval_floor_required"
    assert saved["status"] == "awaiting_approval" and saved["started_at"] is None
    assert started == []

    harness.runs.upsert_item(record)
    executed = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": CONVERSATION, "run_id": record["id"],
    }, buffered=True)
    saved = harness.runs.read_item(record["id"], CONVERSATION)
    assert executed.status_code == 200 and saved["started_at"], _frames(executed)
    assert started == ["run_digest"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
