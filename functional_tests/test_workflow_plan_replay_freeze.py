# test_workflow_plan_replay_freeze.py
"""
Functional test for the plan replay freeze, allowlist and per-run re-authorization.
Version: 0.261.308
Implemented in: 0.261.308

This test ensures that a saved workflow freezes only a completed, approved plan its creator
owns in a private chat, that the versioned allowlist refuses every class it must with a fixed
reason, that the SHA-256 covers the request, the plan and the seeds, and that every run
re-authorizes the creator: the settings, the personal scope, the creator, the hash, each
capability against the current admin list, and every source the plan reads. Background runs
carry no roles, so a manual run and a scheduled run are allowed exactly the same capabilities.

Checks raise AssertionError explicitly so they still run under ``python -O``.
"""

import importlib
import inspect
import sys
from copy import deepcopy

import pytest

from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.versioning import assert_app_version_at_least


OWNER = "owner"
REPLAY_SETTINGS = {
    "enable_workflow_plan_replay": True,
    "enable_chat_orchestration": True,
    "allow_user_workflows": True,
    "enable_user_workspace": True,
    "enable_group_workspaces": True,
    "enable_public_workspaces": True,
    "enable_image_generation": True,
    "enable_web_search": True,
    "chat_orchestration_enabled_capabilities": [],
}
HOSTILE_TITLE = '<img src=x onerror="alert(1)">Step"\'</script>'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


@pytest.fixture
def replay(initialized_application):
    return importlib.import_module("functions_workflow_plan_replay")


def _step(capability_id, number=1, **arguments):
    return {
        "step_id": f"s{number}", "capability_id": capability_id, "title": f"Step {number}",
        "arguments": arguments, "depends_on": [], "enabled": True,
    }


def _plan(*steps, **extra):
    return {"plan_id": "plan-1", "planner_contract_version": 2, "steps": list(steps), **extra}


def _record(**changes):
    record = {
        "id": "run-1", "user_id": OWNER, "conversation_id": "conversation-1",
        "status": "completed", "outcome": "completed", "approval": {"state": "approved"},
        "plan": _plan(_step("compose", instruction="Summarize the notes.")),
        "user_message": "Summarize my notes",
        "resolved_message": "Summarize my notes\n\nCurrent date and time: Monday, 28 September 2026, 09:00 (UTC)",
        "seeds": {"doc_scope": "personal"}, "answered_questions": [], "conversation_context": {},
        "time_zone": "America/New_York",
    }
    record.update(changes)
    return record


def _conversation(**changes):
    conversation = {"id": "conversation-1", "user_id": OWNER, "title": "Notes"}
    conversation.update(changes)
    return conversation


def _codes(refusals):
    return [refusal["code"] for refusal in refusals]


def _task(replay, record=None, settings=None):
    freeze = replay.freeze_source_run(record or _record(), _conversation(), OWNER, settings or REPLAY_SETTINGS)
    require(freeze["refusals"] == [], f"The fixture plan must be eligible: {freeze['refusals']}")
    payload = replay.build_plan_replay_payload(freeze, OWNER, "2026-09-28T09:00:00+00:00")
    return replay.attach_plan_replay({"id": "task-1", "type": "instructions"}, payload)


def _workflow(**changes):
    workflow = {"id": "workflow-1", "user_id": OWNER, "created_by": OWNER, "scope": "personal"}
    workflow.update(changes)
    return workflow


def _refused(replay, call, code):
    with pytest.raises((replay.PlanReplayRefused, replay.PlanReplaySaveError)) as caught:
        call()
    require(caught.value.code == code, f"Expected {code}, got {caught.value.code}: {caught.value.public_message}")
    require(caught.value.public_message, "Every refusal carries fixed public text.")
    return caught.value


def _rehash(replay, task):
    data = task["plan_replay"]
    digest = replay.plan_replay_sha256(data["request"], data["frozen_plan"], data["frozen_seeds"])
    data["plan_sha256"] = digest
    data["approval"]["plan_sha256"] = digest
    return task


def test_version_includes_plan_replay():
    assert_app_version_at_least("0.261.308")


def test_the_allowlist_is_versioned_and_names_a_reason_for_each_entry(replay):
    require(replay.PLAN_REPLAY_ALLOWLIST_VERSION == "plan-replay-allowlist-v1", "The allowlist is versioned.")
    require(set(replay.REPLAYABLE_CAPABILITIES) == {
        "document_search", "document_analyze", "document_compare", "document_merge",
        "tabular_inspect", "compose", "generate_image",
    }, "Only the seven reviewed capabilities may repeat.")
    for capability_id, reason in replay.REPLAYABLE_CAPABILITIES.items():
        require(isinstance(reason, str) and len(reason) > 20, f"{capability_id} needs a written reason.")
    registry = importlib.import_module("functions_orchestration_registry")
    never = (
        set(replay.WORKFLOW_CAPABILITIES) | set(registry.approval_floor_capability_ids())
        | set(registry.external_effect_capability_ids()) | set(replay.ROLE_REQUIRED_CAPABILITIES)
        | set(replay.WAIT_CAPABILITIES) | {"deep_research", "url_fetch", "tabular_merge"}
    )
    require(not never & set(replay.REPLAYABLE_CAPABILITIES), "A refused class leaked into the allowlist.")
    require(set(registry.all_capability_ids()) >= set(replay.REPLAYABLE_CAPABILITIES), "Every entry is a real capability.")


@pytest.mark.parametrize("capability_id", [
    "document_search", "document_analyze", "document_compare", "document_merge",
    "tabular_inspect", "compose", "generate_image",
])
def test_each_allowed_capability_passes_classification(replay, capability_id):
    refusals = replay.classify_plan_steps(_plan(_step(capability_id)))
    require(refusals == [], f"{capability_id} must be replayable: {refusals}")


@pytest.mark.parametrize("capability_id, arguments, code, fragment", [
    ("workflow_propose", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("workflow_run", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("workflow_results", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("workflow_handoff", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("action_invoke", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("agent_invoke", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("deep_research", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("url_fetch", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("tabular_merge", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("made_up_capability", {}, "capability_not_replayable", "can't be repeated by a saved workflow."),
    ("web_search", {}, "role_required", "needs your signed-in session, which a repeated run doesn't have."),
    ("tabular_analyze", {}, "replay_wait_unsupported", "finishes after the plan stops waiting"),
    ("render_file", {}, "replay_wait_unsupported", "finishes after the plan stops waiting"),
    ("generate_image", {"reference_document_ids": ["doc-1"]}, "capability_not_replayable", "edits a reference image"),
    ("generate_image", {"reference_message_ids": ["msg-1"]}, "capability_not_replayable", "edits a reference image"),
])
def test_each_refused_class_has_its_fixed_reason(replay, capability_id, arguments, code, fragment):
    step = _step(capability_id, **arguments)
    step["title"] = HOSTILE_TITLE
    refusals = replay.classify_plan_steps(_plan(step))
    require(_codes(refusals) == [code], f"{capability_id}: {refusals}")
    message = refusals[0]["message"]
    label = replay.capability_label(capability_id)
    require(message.startswith(f"Step 1 ({label})"), f"The message names the registry label: {message}")
    require(fragment in message, f"{capability_id}: {message}")
    require(HOSTILE_TITLE not in message and "<img" not in message, "A model-written title never reaches the text.")
    require(refusals[0]["step_number"] == 1 and refusals[0]["capability_id"] == capability_id, "The step is named.")


def test_a_compose_step_that_offers_an_image_is_refused(replay):
    registry = importlib.import_module("functions_orchestration_registry")
    refusals = replay.classify_plan_steps(_plan(_step("compose", visuals=[registry.VISUAL_IMAGE_PROPOSAL])))
    require(_codes(refusals) == ["capability_not_replayable"], str(refusals))
    require("offers an image for you to accept" in refusals[0]["message"], refusals[0]["message"])


@pytest.mark.parametrize("wait_kind", [
    "native_tabular_compute", "orchestration_output", "orchestration_result",
    # Phase 6c's in-plan wait: SAVED_WORKFLOW_RUN_WAIT_KIND in functions_orchestration_workflow_run_wait.py.
    "saved_workflow_run",
])
def test_every_refused_wait_kind_is_refused(replay, wait_kind):
    nested = _step("compose")
    nested["inputs"] = {"source": {"binding": {"wait_kind": wait_kind}}}
    for step in (_step("compose", wait_kind=wait_kind), nested):
        refusals = replay.classify_plan_steps(_plan(step))
        require(_codes(refusals) == ["replay_wait_unsupported"], f"{wait_kind}: {refusals}")
        require("waits for work to finish after the plan stops" in refusals[0]["message"], refusals[0]["message"])


def test_the_phase_6c_saved_workflow_run_wait_is_refused(replay):
    # Mirrors SAVED_WORKFLOW_RUN_WAIT_KIND from Phase 6c, which is not on this base yet.
    require(replay.SAVED_WORKFLOW_RUN_WAIT_KIND == "saved_workflow_run", "The constant matches Phase 6c.")
    refusals = replay.classify_plan_steps(_plan(_step("document_search", kind="saved_workflow_run")))
    require(_codes(refusals) == ["replay_wait_unsupported"], str(refusals))


def _waited_run_plan(**extra):
    """A plan as Phase 6c stores it: one workflow_run step that waits, read by a compose step."""
    summarize = _step("compose", 2, instruction="Summarize the workflow's results.")
    summarize["depends_on"] = ["s1"]
    return _plan(_step("workflow_run", 1, workflow="w1"), summarize, **extra)


def test_a_waited_workflow_run_step_is_refused_as_a_wait_when_frozen(replay):
    label = replay.capability_label("workflow_run")
    # Phase 6c's stored shape: plan["workflow_run_waits"] = {step_id: {"version": 1, "workflow": handle}}.
    marker = {"s1": {"version": 1, "workflow": "w1"}}
    record = _record(plan=_waited_run_plan(workflow_run_waits=marker))
    freeze = replay.freeze_source_run(record, _conversation(), OWNER, REPLAY_SETTINGS)
    refusals = freeze["refusals"]
    require(_codes(refusals) == ["replay_wait_unsupported"], f"One refusal for the waited step: {refusals}")
    require(refusals[0]["step_number"] == 1 and refusals[0]["step_id"] == "s1", str(refusals))
    require(refusals[0]["capability_id"] == "workflow_run", str(refusals))
    require(
        refusals[0]["message"]
        == f"Step 1 ({label}) waits for a saved workflow run to finish, which a repeated run can't do yet.",
        refusals[0]["message"],
    )
    require("workflow_run_waits" not in freeze["frozen_plan"], "The frozen plan never carries the marker.")
    preview = replay.build_plan_replay_preview(freeze, REPLAY_SETTINGS)
    require(preview["eligible"] is False and preview["refusals"] == refusals, str(preview))

    unmarked = replay.freeze_source_run(_record(plan=_waited_run_plan()), _conversation(), OWNER, REPLAY_SETTINGS)
    require(_codes(unmarked["refusals"]) == ["capability_not_replayable"],
            f"Without the marker the run step is refused as a workflow step: {unmarked['refusals']}")


@pytest.mark.parametrize("marker", [
    {"missing": {"version": 1, "workflow": "w1"}},
    {"s2": {"version": 1, "workflow": "w1"}},
    ["s1"],
    "s1",
    True,
])
def test_a_wait_marker_that_matches_no_running_step_refuses_the_whole_plan(replay, marker):
    switched_off = _step("workflow_run", 2, workflow="w1")
    switched_off["enabled"] = False
    plan = _plan(_step("compose", 1, instruction="Summarize the notes."), switched_off, workflow_run_waits=marker)
    freeze = replay.freeze_source_run(_record(plan=plan), _conversation(), OWNER, REPLAY_SETTINGS)
    refusals = freeze["refusals"]
    require(_codes(refusals) == ["replay_wait_unsupported"], f"{marker!r}: {refusals}")
    require(refusals[0]["step_number"] == 0 and refusals[0]["step_id"] == "", str(refusals))
    require(
        refusals[0]["message"]
        == "This plan waits for a saved workflow run to finish, which a repeated run can't do yet.",
        refusals[0]["message"],
    )


@pytest.mark.parametrize("marker", [None, {}])
def test_an_absent_or_empty_wait_marker_changes_nothing(replay, marker):
    baseline = replay.freeze_source_run(_record(), _conversation(), OWNER, REPLAY_SETTINGS)
    record = _record(plan=_plan(_step("compose", instruction="Summarize the notes."), workflow_run_waits=marker))
    freeze = replay.freeze_source_run(record, _conversation(), OWNER, REPLAY_SETTINGS)
    require(freeze["refusals"] == [], f"{marker!r}: {freeze['refusals']}")
    require(freeze["plan_sha256"] == baseline["plan_sha256"], "An empty marker leaves the frozen plan unchanged.")


def test_a_merge_that_feeds_render_file_is_refused_naming_render_file(replay):
    label = replay.capability_label("render_file")
    plan = _plan(
        _step("document_merge", 1), _step("render_file", 2, output_format="docx"),
        deliverables=[{"id": "merged", "kind": "file", "format": "docx"}],
    )
    refusals = replay.classify_plan_steps(plan)
    require(_codes(refusals) == ["replay_wait_unsupported", "replay_wait_unsupported"], str(refusals))
    require(refusals[0]["message"].startswith(f"Step 2 ({label})"), refusals[0]["message"])
    require(refusals[1]["message"] == f"This plan creates a file ({label}), which a repeated run can't do yet.",
            refusals[1]["message"])
    file_only = replay.classify_plan_steps(_plan(_step("document_merge"), deliverables=[{"id": "f", "kind": "file"}]))
    require(_codes(file_only) == ["replay_wait_unsupported"] and label in file_only[0]["message"], str(file_only))


def test_answer_image_and_visual_deliverables_are_replayable(replay):
    implicit = importlib.import_module("functions_orchestration_deliverables").implicit_answer_deliverable()
    for kinds in ([implicit], [implicit, {"id": "i", "kind": "image"}, {"id": "c", "kind": "chart"},
                               {"id": "d", "kind": "diagram"}]):
        refusals = replay.classify_plan_steps(_plan(_step("compose"), deliverables=kinds))
        require(refusals == [], f"{kinds}: {refusals}")
    refusals = replay.classify_plan_steps(_plan(_step("compose"), deliverables=[{"id": "w", "kind": "workflow"}]))
    require(_codes(refusals) == ["capability_not_replayable"], str(refusals))


def test_the_step_budget_and_an_empty_plan(replay):
    nine = _plan(*[_step("compose", number) for number in range(1, 10)])
    refusals = replay.classify_plan_steps(nine)
    require(_codes(refusals) == ["replay_budget_exceeded"], str(refusals))
    require(refusals[0]["message"] == "A saved plan can repeat at most 8 steps.", refusals[0]["message"])
    eight = _plan(*[_step("compose", number) for number in range(1, 9)])
    require(replay.classify_plan_steps(eight) == [], "Eight steps fit the budget.")
    empty = replay.classify_plan_steps(_plan())
    require(_codes(empty) == ["capability_unavailable"] and empty[0]["message"] == "This plan has no steps to repeat.",
            str(empty))
    disabled = _step("web_search", 2)
    disabled["enabled"] = False
    require(replay.classify_plan_steps(_plan(_step("compose"), disabled)) == [], "A turned-off step never runs.")


def test_a_completed_harness_plan_freezes_with_a_stable_hash(harness, replay):
    harness.create(replies=["The prepared content."], final_response=input_binding("prepare"))
    harness.prepare().execute()
    record = harness.read()
    require(record["status"] == "completed", str(record.get("failure")))
    require(record["plan"].get("deliverables"), "A compiled plan always declares the implicit answer.")
    settings = {**harness.settings, **REPLAY_SETTINGS}
    first = replay.freeze_source_run(record, harness.conversation, OWNER, settings)
    second = replay.freeze_source_run(deepcopy(record), deepcopy(harness.conversation), OWNER, settings)
    require(first["refusals"] == [], f"A completed compose plan is replayable: {first['refusals']}")
    require(first["request"] == harness.turn["content"], first["request"])
    require(len(first["plan_sha256"]) == 64 and first["plan_sha256"] == second["plan_sha256"], "The hash is stable.")
    require(first["frozen_plan"] == replay.normalize_plan_contract(record["plan"]), "The plan is normalized.")
    require([step["capability_id"] for step in first["frozen_plan"]["steps"]] == ["compose"], "Steps are kept.")
    require(first["source_run_id"] == "run-1" and first["source_conversation_id"] == "conversation-1", "Provenance.")


SHARED_CONVERSATIONS = [
    {"user_id": "someone-else"},
    {"collaboration_conversation_id": "collab-1"},
    {"is_hidden": True},
    {"chat_type": "personal_multi_user"},
    {"converted_to_collaboration_at": "2026-09-28T09:00:00+00:00"},
]


@pytest.mark.parametrize("changes", SHARED_CONVERSATIONS)
def test_only_a_private_conversation_the_creator_owns_can_be_frozen(replay, changes):
    _refused(replay, lambda: replay.freeze_source_run(_record(), _conversation(**changes), OWNER, REPLAY_SETTINGS),
             "shared_conversation_not_allowed")


@pytest.mark.parametrize("changes, code", [
    ({"user_id": "someone-else"}, "creator_mismatch"),
    ({"status": "failed"}, "source_run_not_eligible"),
    ({"status": "running"}, "source_run_not_eligible"),
    ({"outcome": "cancelled"}, "source_run_not_eligible"),
    ({"approval": {"state": "pending"}}, "source_run_not_eligible"),
    ({"failure": {"code": "x"}}, "source_run_not_eligible"),
    ({"failures": [{"code": "x"}]}, "source_run_not_eligible"),
    ({"workflow_replay": {"workflow_id": "workflow-1"}}, "source_run_not_eligible"),
    ({"plan": None}, "source_run_not_eligible"),
    ({"user_message": "", "resolved_message": ""}, "source_run_not_eligible"),
    ({"answered_questions": [{"question": "Which?", "answer": "This"}]}, "elicitation_not_replayable"),
    ({"seeds": {"elicitation_references": ["q-1"]}}, "elicitation_not_replayable"),
    ({"plan": _plan(_step("compose"), elicitation={"question": "Which?"})}, "elicitation_not_replayable"),
    ({"result_aliases": [{"alias": "r1"}]}, "conversation_context_not_replayable"),
    ({"conversation_context": {"analysis_result_contexts": [{}]}}, "conversation_context_not_replayable"),
    ({"seeds": {"doc_scope": "everything"}}, "conversation_context_not_replayable"),
])
def test_freeze_refuses_runs_it_must_not_repeat(replay, changes, code):
    _refused(replay, lambda: replay.freeze_source_run(_record(**changes), _conversation(), OWNER, REPLAY_SETTINGS),
             code)


def test_freeze_reports_every_refused_step_instead_of_saving(replay):
    record = _record(plan=_plan(_step("web_search", 1), _step("workflow_run", 2), _step("compose", 3)))
    freeze = replay.freeze_source_run(record, _conversation(), OWNER, REPLAY_SETTINGS)
    require(_codes(freeze["refusals"]) == ["role_required", "capability_not_replayable"], str(freeze["refusals"]))
    require([refusal["step_number"] for refusal in freeze["refusals"]] == [1, 2], "Each refusal names its step.")
    preview = replay.build_plan_replay_preview(freeze, REPLAY_SETTINGS)
    require(preview["eligible"] is False and len(preview["steps"]) == 3, str(preview))


def test_the_request_drops_only_the_trailing_run_time_line(replay):
    freeze = replay.freeze_source_run(_record(), _conversation(), OWNER, REPLAY_SETTINGS)
    require(freeze["request"] == "Summarize my notes", freeze["request"])
    kept = "Current date and time: Monday, 28 September 2026, 09:00 (UTC)\nThen summarize."
    freeze = replay.freeze_source_run(_record(resolved_message=kept), _conversation(), OWNER, REPLAY_SETTINGS)
    require(freeze["request"] == kept, "A line the user wrote mid-request is kept as written.")


def test_the_hash_covers_the_request_plan_and_seeds(replay):
    plan = _plan(_step("compose", instruction="Summarize."))
    seeds = {"doc_scope": "personal", "model_deployment": "gpt-4o"}
    base = replay.plan_replay_sha256("Summarize my notes", plan, seeds)
    reordered = {"steps": plan["steps"], "planner_contract_version": 2, "plan_id": "plan-1"}
    require(replay.plan_replay_sha256("Summarize my notes", reordered, dict(reversed(seeds.items()))) == base,
            "Key order never changes the hash.")
    edited_plan = deepcopy(plan)
    edited_plan["steps"][0]["arguments"]["instruction"] = "Email the notes to everyone."
    for changed in (
        replay.plan_replay_sha256("Summarize my notes!", plan, seeds),
        replay.plan_replay_sha256("Summarize my notes", edited_plan, seeds),
        replay.plan_replay_sha256("Summarize my notes", plan, {**seeds, "model_deployment": "other"}),
        replay.plan_replay_sha256("Summarize my notes", plan, {**seeds, "document_ids": ["doc-9"]}),
    ):
        require(changed != base, "Every frozen input changes the hash.")


def test_the_stored_task_runs_only_while_its_hash_is_unchanged(replay):
    task = _task(replay)
    authorized = replay.authorize_plan_replay_run(_workflow(), task, REPLAY_SETTINGS)
    require(authorized["user_id"] == OWNER and authorized["plan_sha256"] == task["plan_replay"]["plan_sha256"],
            str(authorized))
    edits = [
        lambda data: data["frozen_plan"]["steps"][0].__setitem__("title", "Rewritten"),
        lambda data: data["frozen_plan"]["steps"][0]["arguments"].__setitem__("instruction", "Do more."),
        lambda data: data["frozen_plan"]["steps"].append(_step("compose", 2)),
        lambda data: data.__setitem__("request", "Something else"),
        lambda data: data["frozen_seeds"].__setitem__("model_deployment", "other"),
        lambda data: data["approval"].__setitem__("plan_sha256", "0" * 64),
        lambda data: data.__setitem__("plan_sha256", "0" * 64),
    ]
    for edit in edits:
        edited = deepcopy(task)
        edit(edited["plan_replay"])
        _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), edited, REPLAY_SETTINGS),
                 "plan_hash_mismatch")
    injected = deepcopy(task)
    injected["plan_replay"]["frozen_plan"]["steps"][0]["injected"] = "send email"
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), _rehash(replay, injected), REPLAY_SETTINGS),
             "plan_hash_mismatch")


def test_any_edit_to_the_frozen_plan_through_a_save_is_refused(replay):
    task = _task(replay)
    existing = {**_workflow(), "name": "Weekly notes", "tasks": [task]}
    edited_task = deepcopy(task)
    edited_task["plan_replay"]["frozen_plan"]["steps"][0]["title"] = "Rewritten"
    _refused(replay, lambda: replay.normalize_plan_replay_update(existing, {"name": "x", "tasks": [edited_task]}),
             "plan_replay_read_only")
    kept = replay.normalize_plan_replay_update(existing, {"name": "Renamed", "tasks": [deepcopy(task)]})
    require(kept["name"] == "Renamed", "The name stays editable.")


@pytest.mark.parametrize("setting, code", [
    ("enable_workflow_plan_replay", "replay_disabled"),
    ("enable_chat_orchestration", "orchestration_disabled"),
    ("allow_user_workflows", "personal_workflows_disabled"),
])
def test_every_run_rechecks_the_settings(replay, setting, code):
    task = _task(replay)
    for value in (False, None, "true", 1):
        settings = {**REPLAY_SETTINGS, setting: value}
        _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), task, settings), code)
    missing = {key: value for key, value in REPLAY_SETTINGS.items() if key != setting}
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), task, missing), code)


@pytest.mark.parametrize("changes", [{"group_id": "group-1"}, {"scope": "group"}, {"scope": "GROUP"}])
def test_group_workflows_are_refused_at_run_time(replay, changes):
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(**changes), _task(replay), REPLAY_SETTINGS),
             "group_not_supported")


def test_group_workflows_are_refused_at_creation(replay):
    builder = importlib.import_module("functions_group_workflows").build_group_workflow_document
    for payload in ({"name": "x", "tasks": [_task(replay)]}, {"name": "x", "plan_replay": {}}):
        _refused(replay, lambda: builder("group-1", payload, OWNER, settings=REPLAY_SETTINGS), "group_not_supported")


def test_only_the_creator_is_ever_the_actor(replay):
    task = _task(replay)
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(created_by="someone-else"), task,
                                                              REPLAY_SETTINGS), "creator_mismatch")
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(user_id="someone-else"), task,
                                                              REPLAY_SETTINGS), "creator_mismatch")
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(user_id=""), task, REPLAY_SETTINGS),
             "creator_mismatch")
    for path in ("provenance", "approval"):
        edited = deepcopy(task)
        key = "created_by" if path == "provenance" else "approved_by"
        edited["plan_replay"][path][key] = "someone-else"
        _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), edited, REPLAY_SETTINGS),
                 "creator_mismatch")
    with pytest.raises(replay.PlanReplaySaveError) as caught:
        replay.freeze_source_run(_record(), _conversation(), "someone-else", REPLAY_SETTINGS)
    require(caught.value.code == "creator_mismatch", caught.value.code)


@pytest.mark.parametrize("key, value", [("version", 2), ("allowlist_version", "plan-replay-allowlist-v0")])
def test_an_unknown_task_or_allowlist_version_is_refused(replay, key, value):
    task = _task(replay)
    task["plan_replay"][key] = value
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), task, REPLAY_SETTINGS),
             "allowlist_version_unsupported")


def test_a_capability_the_admin_removed_or_turned_off_is_refused(replay, monkeypatch):
    images = importlib.import_module("functions_orchestration_images")
    monkeypatch.setattr(images, "image_generation_readiness",
                        lambda settings: {"status": "available", "max_reference_images": 0})
    record = _record(plan=_plan(_step("document_search", query="notes"), _step("compose", 2)))
    task = _task(replay, record)
    narrowed = {**REPLAY_SETTINGS, "chat_orchestration_enabled_capabilities": ["compose"]}
    refused = _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), task, narrowed),
                       "capability_unavailable")
    require(refused.public_message == "Step 1 (Search documents) is turned off or no longer available.",
            refused.public_message)
    gated = {**REPLAY_SETTINGS, "enable_user_workspace": False, "enable_group_workspaces": False,
             "enable_public_workspaces": False}
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), task, gated), "capability_unavailable")
    image = _task(replay, _record(plan=_plan(_step("generate_image", prompt="A chart"))), REPLAY_SETTINGS)
    _refused(replay, lambda: replay.authorize_plan_replay_run(
        _workflow(), image, {**REPLAY_SETTINGS, "enable_image_generation": False}), "capability_unavailable")


def test_a_stored_role_gated_step_is_refused_before_step_one(replay):
    task = _task(replay)
    task["plan_replay"]["frozen_plan"]["steps"].insert(0, replay.normalize_plan_contract(
        _plan(_step("web_search", 0, query="news")))["steps"][0])
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), _rehash(replay, task), REPLAY_SETTINGS),
             "role_required")


def test_a_stored_plan_that_asks_a_question_is_refused_before_step_one(replay):
    # Normalizing keeps step arguments, so a question reference there survives into a stored plan.
    in_plan = _task(replay)
    in_plan["plan_replay"]["frozen_plan"]["steps"][0]["arguments"]["elicitation_ref"] = "q-1"
    in_seeds = _task(replay)
    in_seeds["plan_replay"]["frozen_seeds"]["elicitation_references"] = ["q-1"]
    for task in (in_plan, in_seeds):
        _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), _rehash(replay, task), REPLAY_SETTINGS),
                 "elicitation_not_replayable")


def test_manual_and_scheduled_runs_are_allowed_the_same_capabilities(replay, monkeypatch):
    require(list(inspect.signature(replay.authorize_plan_replay_run).parameters) == ["workflow", "task", "settings"],
            "Run authorization never takes the trigger's roles.")
    require("user_roles" not in inspect.signature(replay.execute_plan_replay_task).parameters,
            "The executor never takes the trigger's roles.")
    contexts = []
    original = replay.resolve_available_capabilities

    def spy(*args, **kwargs):
        contexts.append(deepcopy(kwargs.get("request_context")))
        return original(*args, **kwargs)

    monkeypatch.setattr(replay, "resolve_available_capabilities", spy)
    task = _task(replay, _record(plan=_plan(_step("document_search", query="notes"), _step("compose", 2))))
    replay.authorize_plan_replay_run(_workflow(), task, REPLAY_SETTINGS)
    replay.authorize_plan_replay_run(_workflow(), task, REPLAY_SETTINGS)
    require(contexts and all(context["user_roles"] == [] and context["user_enable_agents"] is False
                             and context["user_id"] == OWNER for context in contexts), str(contexts))
    require(all(context == contexts[0] for context in contexts), "Every trigger sees the same request context.")


class _SourceDoubles:
    def __init__(self, monkeypatch):
        self.calls = []
        self.group = {"id": "group-1", "status": "active"}
        self.member_role = "user"
        self.group_allowed = True
        self.workspace = {"id": "public-1", "status": "active"}
        self.workspace_allowed = True
        self.manifest_status = "authorized"
        self.manifest_error = None
        group = importlib.import_module("functions_group")
        public = importlib.import_module("functions_public_workspaces")
        sources = importlib.import_module("functions_mixed_source_orchestration")
        monkeypatch.setattr(group, "find_group_by_id", lambda group_id: self.group)
        monkeypatch.setattr(group, "get_user_role_in_group", lambda group_doc, user_id: self.member_role)
        monkeypatch.setattr(group, "check_group_status_allows_operation",
                            lambda group_doc, operation: (self.group_allowed, "status"))
        monkeypatch.setattr(public, "find_public_workspace_by_id", lambda workspace_id: self.workspace)
        monkeypatch.setattr(public, "check_public_workspace_status_allows_operation",
                            lambda workspace, operation: (self.workspace_allowed, "status"))
        monkeypatch.setattr(sources, "resolve_authorized_source_manifest", self.manifest)

    def manifest(self, document_ids, user_id, **kwargs):
        self.calls.append({"document_ids": list(document_ids), "user_id": user_id, **kwargs})
        if self.manifest_error:
            raise self.manifest_error
        return [{"document_id": document_id, "authorization_status": self.manifest_status}
                for document_id in document_ids]


SOURCE_SEEDS = {
    "doc_scope": "all", "document_ids": ["doc-1"], "active_group_ids": ["group-1"],
    "active_public_workspace_ids": ["public-1"],
}


def test_every_source_is_rechecked_as_the_creator(replay, monkeypatch):
    doubles = _SourceDoubles(monkeypatch)
    task = _task(replay, _record(seeds=dict(SOURCE_SEEDS)))
    replay.authorize_plan_replay_run(_workflow(), task, REPLAY_SETTINGS)
    require(doubles.calls == [{
        "document_ids": ["doc-1"], "user_id": OWNER, "conversation_id": None, "doc_scope": "all",
        "active_group_ids": ["group-1"], "active_public_workspace_ids": ["public-1"],
    }], str(doubles.calls))
    lost = [
        ("member_role", None),
        ("group", None),
        ("group_allowed", False),
        ("workspace", None),
        ("workspace_allowed", False),
        ("manifest_status", "unauthorized"),
        ("manifest_error", PermissionError("gone")),
        ("manifest_error", LookupError("gone")),
    ]
    for attribute, value in lost:
        original = getattr(doubles, attribute)
        setattr(doubles, attribute, value)
        _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), task, REPLAY_SETTINGS),
                 "source_unavailable")
        setattr(doubles, attribute, original)
    for setting in ("enable_group_workspaces", "enable_public_workspaces"):
        for value in (False, None):
            _refused(replay, lambda: replay.authorize_plan_replay_run(
                _workflow(), task, {**REPLAY_SETTINGS, setting: value}), "source_unavailable")


def test_plan_document_ids_are_rechecked_too(replay, monkeypatch):
    doubles = _SourceDoubles(monkeypatch)
    plan = _plan(_step("document_analyze", document_ids=["doc-7"], question="Totals?"), _step("compose", 2))
    task = _task(replay, _record(plan=plan))
    doubles.manifest_status = "unauthorized"
    _refused(replay, lambda: replay.authorize_plan_replay_run(_workflow(), task, REPLAY_SETTINGS),
             "source_unavailable")
    require(doubles.calls and "doc-7" in doubles.calls[-1]["document_ids"], str(doubles.calls))


def test_saving_rechecks_sources_before_creating_the_workflow(replay, monkeypatch):
    doubles = _SourceDoubles(monkeypatch)
    personal = importlib.import_module("functions_personal_workflows")

    def must_not_create(*args, **kwargs):
        raise AssertionError("No workflow is created for a source the creator can't reach.")

    monkeypatch.setattr(personal, "create_personal_workflow_if_absent", must_not_create)
    record = _record(seeds=dict(SOURCE_SEEDS))
    freeze = replay.freeze_source_run(record, _conversation(), OWNER, REPLAY_SETTINGS)
    doubles.manifest_status = "unauthorized"
    body = {"conversation_id": "conversation-1", "plan_sha256": freeze["plan_sha256"]}
    _refused(replay, lambda: replay.create_plan_replay_workflow(
        OWNER, "run-1", body, REPLAY_SETTINGS,
        read_run=lambda run_id, user_id, conversation_id: deepcopy(record),
        read_conversation=lambda conversation_id: _conversation(),
    ), "source_unavailable")
    stale = {**body, "plan_sha256": "0" * 64}
    doubles.manifest_status = "authorized"
    _refused(replay, lambda: replay.create_plan_replay_workflow(
        OWNER, "run-1", stale, REPLAY_SETTINGS,
        read_run=lambda run_id, user_id, conversation_id: deepcopy(record),
        read_conversation=lambda conversation_id: _conversation(),
    ), "plan_hash_mismatch")


def test_saving_requires_the_settings_and_a_conversation(replay):
    _refused(replay, lambda: replay.create_plan_replay_workflow(
        OWNER, "run-1", {"conversation_id": "conversation-1"}, {**REPLAY_SETTINGS, "enable_workflow_plan_replay": False},
    ), "replay_disabled")
    _refused(replay, lambda: replay.create_plan_replay_workflow(OWNER, "run-1", {}, REPLAY_SETTINGS),
             "source_run_not_eligible")


def test_refusal_text_is_fixed_and_mapped_to_a_status(replay):
    for code, message in replay.REFUSAL_MESSAGES.items():
        require(isinstance(message, str) and message and "{" not in message, f"{code} has fixed text.")
        body, status = replay.plan_replay_error_response(code)
        require(body["code"] == code and body["error"] == message and status in (403, 404, 409, 422, 429, 503),
                f"{code}: {body} {status}")
    require(replay.plan_replay_error_response("creator_mismatch")[1] == 403, "A creator mismatch is forbidden.")
    require(replay.plan_replay_error_response("plan_hash_mismatch")[1] == 409, "A stale hash conflicts.")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:langsmith_plugin", "-p", "no:cacheprovider"]))
