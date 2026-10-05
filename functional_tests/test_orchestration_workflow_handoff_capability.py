#!/usr/bin/env python3
# test_orchestration_workflow_handoff_capability.py
"""
Functional test for the workflow_handoff capability's registry entry, gates and plan rules.
Version: 0.261.239
Implemented in: 0.261.239

This test ensures that ``workflow_handoff``:

- is a Reason capability with a manual approval floor, one step per plan and a static blueprint
  input, with no external effects and no transient retry, so an interrupted hand-off step never
  asks the user to confirm a retry: the step only checks the blueprint, and the accept route
  creates and queues the workflow later;
- stays out of the deployment, with no unavailable reason, until its own setting is exactly
  True, whatever the capability allowlist says, so an upgrade never turns it on;
- is offered only when every hand-off gate passes, and is otherwise left out silently: the
  registry records no reason for it, and the browser's capability list names it only when every
  deployment gate passes;
- reports a closed reason from its request gate, and fails closed with a content-free log entry
  when that check raises, without stopping the rest of the plan;
- is refused when mixed with workflow_propose or workflow_run, when it takes inputs, when another
  step or the answer reads it, when it appears twice, when its arguments break the contract and
  when the request did not offer it;
- always waits for manual approval: normalize_plan saves a hand-off plan as manual with a floor
  whatever mode was asked for, claim_plan_run starts it, and refuses a saved plan whose run
  record or plan no longer reads manual.

Checks use explicit raises, so they hold under ``python -O``.
"""

import importlib
import json
import logging
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_handoff_off_golden import (
    ALLOWLIST,
    ANSWER_STEP,
    FINAL_RESPONSE,
    HANDOFF,
    PROJECTION_WITHOUT_REQUEST,
    RESULTS,
    _settings,
)
from test_orchestration_workflow_handoff_planner import (
    HANDOFF_CAPABILITY,
    NOT_OFFERED,
    _context,
    _handles,
    _handoff_plan,
    _handoff_step,
    _mixed_plan,
    _require,
    _same,
)
from test_orchestration_workflow_results_off_golden import _client_projection
from test_orchestration_workflow_run_approval_floor import CONVERSATION, TURN_CONTEXT, store  # noqa: F401
from test_orchestration_workflow_runs_off_golden import OWNER, PROPOSALS, RUNS, _request_context, _resolution
from test_support.orchestration_harness_execution import input_binding
from test_support.versioning import assert_app_version_at_least


MINIMUM_VERSION = "0.261.239"
INVALID = "workflow_handoff_invalid"
FLOOR = {"mode": "manual", "reason": HANDOFF_CAPABILITY}
INPUTS = {
    "type": "object",
    "properties": {"blueprint": {"type": "object"}},
    "required": ["blueprint"],
    "additionalProperties": False,
}
GATES = ("enable_chat_orchestration", "allow_user_workflows", PROPOSALS, RUNS, RESULTS, HANDOFF)
AVAILABLE = ["compose", "workflow_propose", "workflow_run", HANDOFF_CAPABILITY]
NOT_OFFERING = ["compose", "workflow_propose", "workflow_run"]
# Hand-off is offered with every gate on, and does not depend on the proposal cap or catalogs.
OFFERED = [("on", variant) for variant in ("all_on", "quota_reached", "quota_unreadable", "catalog_unreadable")]
# Values of the hand-off setting that leave the capability out of the deployment.
_MISSING = object()
DORMANT = {"absent": _MISSING, "false": False, "string": "true", "one": 1, "none": None}
ALLOWLISTS = {"everything": [], "names_handoff": [*ALLOWLIST, HANDOFF_CAPABILITY]}
# What the request gate says for each request, in the order the gate checks.
GATE_REASONS = {
    ("on", "all_on"): None,
    ("absent", "all_on"): "workflow_handoff_disabled",
    ("false", "all_on"): "workflow_handoff_disabled",
    ("string", "all_on"): "workflow_handoff_disabled",
    ("on", "orchestration_off"): "workflow_handoff_disabled",
    ("on", "user_workflows_off"): "workflow_handoff_disabled",
    ("on", "proposals_off"): "workflow_handoff_disabled",
    ("on", "runs_off"): "workflow_handoff_disabled",
    ("on", "results_off"): "workflow_results_disabled",
    ("on", "not_allowlisted"): "workflow_handoff_disabled",
    ("on", "role_missing"): "workflow_role_required",
    ("on", "shared_conversation"): "workflow_shared_conversation",
}
CONTEXT_LOG = (
    "[ORCHESTRATION_WORKFLOWS] Workflow hand-off access could not be checked; handing work off is "
    "unavailable for this request."
)
REGISTRY_LOG = "[ORCHESTRATION_REGISTRY] Could not check workflow hand-off access."
SECRET = "Contract for Northwind, ref 4471"


def _registry():
    return importlib.import_module("functions_orchestration_registry")


def _schema():
    return importlib.import_module("functions_orchestration_schema")


def _workflow_context():
    return importlib.import_module("functions_orchestration_workflow_context")


def _descriptor():
    matches = [descriptor for descriptor in _registry().CAPABILITY_REGISTRY if descriptor["id"] == HANDOFF_CAPABILITY]
    _same(len(matches), 1, "the registered workflow_handoff descriptors")
    return matches[0]


def _documents_loop(context):
    documents = _handles(context)["documents"]
    _require(documents, "The fixture must offer a document handle.")
    return {"source": "documents", "documents": documents}


def _query_loop(context):
    scopes = _handles(context)["scopes"]
    _require(scopes, "The fixture must offer a workspace scope handle.")
    return {"source": "workspace_query", "scopes": scopes, "selection": "all_matches", "content": "indemnity"}


def _normalize(settings, context, raw, *, available=AVAILABLE, approval_mode=None):
    return _schema().normalize_plan(
        deepcopy(raw), CONVERSATION, OWNER, settings=deepcopy(settings), approval_mode=approval_mode,
        contract_version=2, turn_id=TURN_CONTEXT["turn_id"], available_capability_ids=list(available),
        workflow_planning=deepcopy(context),
    )


def _rejection(settings, context, raw, **kwargs):
    schema = _schema()
    try:
        _normalize(settings, context, raw, **kwargs)
    except schema.PlanValidationError as exc:
        return exc
    raise AssertionError("The plan was accepted.")


def _recorder(entries):
    def record(message, *_args, **kwargs):
        entries.append({"message": str(message), "level": kwargs.get("level"), "extra": kwargs.get("extra")})
    return record


def _raise(*_args, **_kwargs):
    raise RuntimeError(SECRET)


def _gate_request(context):
    return _request_context(importlib.import_module("functions_orchestration_context"), context)


def _ids(resolution):
    return resolution["capability_ids"]


def _projected_ids(settings):
    return [entry["id"] for entry in _client_projection(settings)]


def test_version_includes_workflow_handoff():
    assert_app_version_at_least(MINIMUM_VERSION)


# ---------------------------------------------------------------------------
# The descriptor
# ---------------------------------------------------------------------------

def test_the_descriptor_is_a_reason_step_with_a_manual_floor_and_one_step_per_plan(modules):
    registry = _registry()
    descriptor = _descriptor()

    _same(registry.CAPABILITY_WORKFLOW_HANDOFF, HANDOFF_CAPABILITY, "the capability id constant")
    _same(registry.WORKFLOW_HANDOFF_SETTING, HANDOFF, "the hand-off setting constant")
    _same((descriptor["role"], registry.ROLE_REASON), ("reason", "reason"), "the role")
    _same(
        (descriptor["approval_floor"], registry.APPROVAL_FLOOR_MANUAL), ("manual", "manual"), "the approval floor",
    )
    _same(descriptor["max_per_plan"], 1, "the steps allowed in one plan")
    _same(descriptor["inputs"], INPUTS, "the static blueprint input")
    _same(descriptor["result_input_kinds"], {}, "the result inputs it consumes")
    _same(descriptor["partial_inputs_supported"], False, "partial inputs")
    _same(descriptor["result_outputs"], {"handoff": "structured-v1"}, "the result outputs")
    _same(descriptor["settings_gates"], GATES, "the settings gates")
    _same((descriptor["settings_gates_any"], descriptor["gate"]), ((), None), "the other deployment gates")
    _require(
        descriptor["request_gate"] is registry._workflow_handoff_request_gate,
        "The request gate must be the hand-off gate.",
    )
    _same(descriptor["dormant_unless_setting"], HANDOFF, "the dormant setting")
    _same(descriptor["silent_when_unavailable"], True, "silence when unavailable")
    _same(descriptor["adapter"], HANDOFF_CAPABILITY, "the adapter")
    _same(descriptor["cost_class"], registry.COST_CLASS_LOW, "the cost class")
    _same(descriptor["result_contract_version"], "workflow-handoff-v1", "the result contract")
    for field in ("external_effects", "retry_on_transient"):
        _require(field not in descriptor, f"workflow_handoff must not set {field}.")

    _require(HANDOFF_CAPABILITY in registry.approval_floor_capability_ids(), "Hand-off must set an approval floor.")
    _require(
        HANDOFF_CAPABILITY not in registry.external_effect_capability_ids(),
        "Hand-off only checks a blueprint; an interrupted step must not ask to confirm external effects.",
    )
    retried = {item["id"] for item in registry.CAPABILITY_REGISTRY if item.get("retry_on_transient")}
    _require(HANDOFF_CAPABILITY not in retried, "Hand-off must not retry as a transient read.")

    ids = registry.all_capability_ids()
    _same(ids.count(HANDOFF_CAPABILITY), 1, "the registered hand-off ids")
    _same(ids.index(HANDOFF_CAPABILITY), ids.index("workflow_results") + 1, "the hand-off's registry position")
    resolved = registry.get_capability(HANDOFF_CAPABILITY)
    _same(
        (resolved["role"], resolved["approval_floor"], resolved["max_per_plan"], resolved["inputs"]),
        ("reason", "manual", 1, INPUTS),
        "the resolved descriptor",
    )
    _require(resolved.get("external_effects") is not True, "The resolved descriptor must have no external effects.")


@pytest.mark.parametrize("arguments,valid", [
    ({"blueprint": {}}, True),
    ({"blueprint": {"name": "Review contracts"}}, True),
    ({}, False),
    ({"blueprint": "Review every contract."}, False),
    ({"blueprint": []}, False),
    ({"blueprint": {}, "inputs": {}}, False),
    ({"blueprint": {}, "workflow": "workflow-1"}, False),
])
def test_the_input_contract_takes_only_a_blueprint_object(modules, arguments, valid):
    _same(Draft202012Validator(_descriptor()["inputs"]).is_valid(arguments), valid, f"the contract for {arguments!r}")


# ---------------------------------------------------------------------------
# Dormant until its own setting is True
# ---------------------------------------------------------------------------

def _with_key(value, allowlist):
    settings = _settings("absent", {"chat_orchestration_enabled_capabilities": deepcopy(allowlist)})
    if value is not _MISSING:
        settings[HANDOFF] = value
    return settings


@pytest.mark.parametrize("allowlist", sorted(ALLOWLISTS))
@pytest.mark.parametrize("state", sorted(DORMANT))
def test_the_capability_is_dormant_until_its_setting_is_exactly_true(modules, state, allowlist):
    registry = _registry()
    _settings_on, context = _context("on")
    settings = _with_key(DORMANT[state], ALLOWLISTS[allowlist])
    baseline_settings = _with_key(_MISSING, ALLOWLISTS[allowlist])

    resolution = _resolution(settings, context)
    _require(HANDOFF_CAPABILITY not in _ids(resolution), f"Hand-off was offered with the setting {state}.")
    _require(HANDOFF_CAPABILITY not in resolution["unavailable"], f"Hand-off recorded a reason with the setting {state}.")
    _same(
        json.dumps(resolution, sort_keys=True), json.dumps(_resolution(baseline_settings, context), sort_keys=True),
        "the resolution compared with the setting absent",
    )
    _require(HANDOFF_CAPABILITY not in _projected_ids(settings), "The browser's list must not name a dormant hand-off.")
    _same(_client_projection(settings), _client_projection(baseline_settings), "the browser's capability list")

    reasons = {}
    deployment = registry.resolve_available_capabilities(
        settings, allowed_ids=settings.get("chat_orchestration_enabled_capabilities"), unavailable=reasons,
        include_runtime_bindings=False,
    )
    _require(
        HANDOFF_CAPABILITY not in [item["id"] for item in deployment] and HANDOFF_CAPABILITY not in reasons,
        "Without a request, a dormant hand-off must be neither offered nor given a reason.",
    )


# ---------------------------------------------------------------------------
# Offered only when every gate passes, and silent otherwise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key_state,variant", OFFERED)
def test_an_offered_hand_off_is_resolved_and_shown_on_the_plan_card(modules, key_state, variant):
    settings, context = _context(key_state, variant)
    descriptor = _descriptor()
    resolution = _resolution(settings, context)

    _same(_ids(resolution)[-1], HANDOFF_CAPABILITY, "the last resolved capability")
    _require(HANDOFF_CAPABILITY not in resolution["unavailable"], "An offered hand-off must have no reason.")
    _same(
        [entry for entry in _client_projection(settings) if entry["id"] == HANDOFF_CAPABILITY],
        [{
            "id": HANDOFF_CAPABILITY, "label": descriptor["label"], "role": "reason",
            "summary": descriptor["summary"], "cost": "low",
        }],
        "the browser's hand-off entry",
    )


@pytest.mark.parametrize("key_state,variant", NOT_OFFERED)
def test_a_request_that_cannot_hand_off_is_not_offered_it_and_gets_no_reason(modules, key_state, variant):
    settings, context = _context(key_state, variant)
    resolution = _resolution(settings, context)

    _require(HANDOFF_CAPABILITY not in _ids(resolution), f"Hand-off was offered for {key_state}/{variant}.")
    _require(
        HANDOFF_CAPABILITY not in resolution["unavailable"],
        f"Hand-off recorded a reason for {key_state}/{variant}: {resolution['unavailable']!r}",
    )
    # The browser's list has no request, so it cannot see a role or a shared conversation.
    _same(
        HANDOFF_CAPABILITY in _projected_ids(settings),
        key_state == "on" and variant in PROJECTION_WITHOUT_REQUEST,
        f"whether the browser's list names hand-off for {key_state}/{variant}",
    )


@pytest.mark.parametrize("key_state,variant", sorted(GATE_REASONS))
def test_the_request_gate_reports_a_closed_reason(modules, key_state, variant):
    registry = _registry()
    settings, context = _context(key_state, variant)
    request_context = _gate_request(context)
    expected = GATE_REASONS[(key_state, variant)]

    reason = _workflow_context().workflow_handoff_unavailable_reason(deepcopy(settings), request_context)
    passed = registry._workflow_handoff_request_gate(deepcopy(settings), request_context)
    _same(reason, expected, f"the hand-off reason for {key_state}/{variant}")
    _same(passed, expected is None, f"the registry's request gate for {key_state}/{variant}")


@pytest.mark.parametrize("planning", ["missing", "not_a_dict", "no_marker", "marker_not_ready", "no_catalog"])
def test_a_request_without_a_ready_hand_off_context_is_refused(modules, planning):
    settings, context = _context("on")
    _off_settings, without_marker = _context("absent")
    _require("workflow_handoff" not in without_marker, "The context built with hand-off off must have no marker.")
    _require(without_marker.get("conversation_private") is True, "The fixture conversation must be private.")
    marker = context["workflow_handoff"]
    planned = {
        "missing": None,
        "not_a_dict": "ready",
        "no_marker": without_marker,
        "marker_not_ready": {**context, "workflow_handoff": {**marker, "ready": False}},
        "no_catalog": {**context, "workflow_handoff": {key: value for key, value in marker.items() if key != "catalog"}},
    }[planning]

    reason = _workflow_context().workflow_handoff_unavailable_reason(deepcopy(settings), _gate_request(planned))
    _same(reason, "workflow_context_unavailable", f"the reason for a {planning} context")
    _require(
        HANDOFF_CAPABILITY not in _ids(_resolution(settings, planned)),
        f"Hand-off was offered with a {planning} context.",
    )


def test_a_hand_off_access_check_that_raises_fails_closed_with_a_content_free_log(modules, monkeypatch):
    wf = _workflow_context()
    settings, context = _context("on")
    entries = []
    monkeypatch.setattr(wf, "log_event", _recorder(entries))
    monkeypatch.setattr(wf, "workflow_handoff_gate", _raise)

    reason = wf.workflow_handoff_unavailable_reason(deepcopy(settings), _gate_request(context))
    _same(reason, "workflow_context_unavailable", "the reason when the check raises")
    _same(entries, [{
        "message": CONTEXT_LOG, "level": logging.WARNING,
        "extra": {"stage": "workflow_planning", "reason": "workflow_context_unavailable", "error_type": "RuntimeError"},
    }], "the log entry")
    _require(SECRET not in json.dumps(entries), "The error text reached the log.")


def test_a_registry_hand_off_check_that_raises_leaves_hand_off_out_and_plans_the_rest(modules, monkeypatch):
    registry = _registry()
    settings, context = _context("on")
    entries = []
    monkeypatch.setattr(registry, "log_event", _recorder(entries))
    monkeypatch.setattr(_workflow_context(), "workflow_handoff_unavailable_reason", _raise)
    expected = {
        "message": REGISTRY_LOG, "level": logging.WARNING,
        "extra": {"reason": "workflow_context_unavailable", "error_type": "RuntimeError"},
    }

    passed = registry._workflow_handoff_request_gate(deepcopy(settings), _gate_request(context))
    _same(passed, False, "the registry's request gate when the check raises")
    _same(entries, [expected], "the log entry")

    resolution = _resolution(settings, context)
    _require(HANDOFF_CAPABILITY not in _ids(resolution), "Hand-off was offered although its check raised.")
    _require(HANDOFF_CAPABILITY not in resolution["unavailable"], "A raising hand-off check must record no reason.")
    _require("compose" in _ids(resolution), "The rest of the plan must still resolve.")
    _same([entry for entry in entries if entry["message"] == REGISTRY_LOG], [expected, expected], "the hand-off log entries")
    _require(SECRET not in json.dumps(entries), "The error text reached the log.")


# ---------------------------------------------------------------------------
# Plan rules
# ---------------------------------------------------------------------------

def test_a_valid_hand_off_plan_normalizes_with_its_static_blueprint(modules):
    settings, context = _context("on")
    only = _normalize(settings, context, _handoff_plan(_handoff_step(_documents_loop(context))))
    mixed = _normalize(settings, context, _mixed_plan(_handoff_step(_query_loop(context))))

    for name, plan, expected in (("hand-off only", only, [HANDOFF_CAPABILITY]), ("mixed", mixed, ["compose", HANDOFF_CAPABILITY])):
        steps = {step["step_id"]: step for step in plan["steps"]}
        _same([step["capability_id"] for step in plan["steps"]], expected, f"the {name} steps")
        handoff = steps["handoff"]
        _same((handoff["role"], handoff["depends_on"], handoff["inputs"]), ("reason", [], {}), f"the {name} hand-off step")
        _same(sorted(handoff["arguments"]), ["blueprint"], f"the {name} hand-off arguments")
    _require("final_response" not in only or only["final_response"] is None, "A hand-off-only plan has no answer.")


@pytest.mark.parametrize("other", ["workflow_propose", "workflow_run"])
@pytest.mark.parametrize("handoff_first", [True, False])
def test_a_hand_off_plan_neither_proposes_nor_starts_another_workflow(modules, other, handoff_first):
    settings, context = _context("on")
    handoff = _handoff_step(_documents_loop(context))
    sibling = {"step_id": "other", "capability_id": other, "arguments": {}, "inputs": {}}
    steps = [handoff, sibling] if handoff_first else [sibling, handoff]

    error = _rejection(settings, context, {**_handoff_plan(handoff), "steps": steps})
    _same((error.code, error.rule), (INVALID, "workflow_handoff_exclusive"), f"the rule for a hand-off with {other}")


def test_the_exclusive_rule_reads_only_plans_with_a_hand_off(modules):
    settings, context = _context("on")
    steps = [
        {"step_id": "propose", "capability_id": "workflow_propose", "arguments": {}, "inputs": {}},
        {"step_id": "run", "capability_id": "workflow_run", "arguments": {}, "inputs": {}},
    ]

    error = _rejection(settings, context, {"kind": "plan", "intent": {"summary": "Two workflows."}, "steps": steps})
    _require(error.rule != "workflow_handoff_exclusive", "A plan without a hand-off must not get the hand-off rule.")


def test_a_request_that_did_not_offer_hand_off_cannot_plan_one(modules):
    settings, context = _context("on")
    handoff = _handoff_step(_documents_loop(context))
    sibling = {"step_id": "other", "capability_id": "workflow_propose", "arguments": {}, "inputs": {}}

    for steps in ([handoff], [handoff, sibling]):
        error = _rejection(
            settings, context, {**_handoff_plan(handoff), "steps": deepcopy(steps)}, available=NOT_OFFERING,
        )
        _same((error.code, error.rule), ("capability_unavailable", None), "the rule for a hand-off that was not offered")


@pytest.mark.parametrize("wiring", ["depends_on", "inputs"])
def test_a_hand_off_step_takes_no_dependencies_or_inputs(modules, wiring):
    settings, context = _context("on")
    fields = (
        {"depends_on": ["answer"]} if wiring == "depends_on"
        else {"inputs": {"answer": {"binding": input_binding("answer")}}}
    )
    plan = {**_mixed_plan(_handoff_step(_documents_loop(context), **fields))}

    error = _rejection(settings, context, plan)
    _same((error.code, error.rule), (INVALID, "workflow_handoff_static_input"), f"the rule for {wiring}")


@pytest.mark.parametrize("wiring", ["input", "depends_on", "final_response"])
def test_no_other_step_or_answer_may_read_a_hand_off(modules, wiring):
    settings, context = _context("on")
    answer, final = deepcopy(ANSWER_STEP), deepcopy(FINAL_RESPONSE)
    if wiring == "input":
        answer["inputs"] = {"handoff": {"binding": input_binding("handoff", "handoff")}}
    elif wiring == "depends_on":
        answer["depends_on"] = ["handoff"]
    else:
        final = input_binding("handoff", "handoff")
    plan = {
        "kind": "plan", "intent": {"summary": "Review every contract."},
        "steps": [_handoff_step(_documents_loop(context)), answer], "final_response": final,
    }

    error = _rejection(settings, context, plan)
    _same((error.code, error.rule), (INVALID, "workflow_handoff_consumed"), f"the rule for a {wiring} reader")


def test_a_plan_hands_off_at_most_once(modules):
    settings, context = _context("on")
    first = _handoff_step(_documents_loop(context))
    second = _handoff_step(_query_loop(context), step_id="handoff_again")

    error = _rejection(settings, context, {**_handoff_plan(first), "steps": [first, second]})
    _same((error.code, error.rule), ("result_step_limit", None), "the rule for a second hand-off")


@pytest.mark.parametrize("arguments", ["extra_argument", "text_blueprint", "no_blueprint"])
def test_hand_off_arguments_must_match_the_contract(modules, arguments):
    settings, context = _context("on")
    step = _handoff_step(_documents_loop(context))
    blueprint = step["arguments"]["blueprint"]
    step["arguments"] = {
        "extra_argument": {"blueprint": blueprint, "workflow": "workflow-1"},
        "text_blueprint": {"blueprint": "Review every contract."},
        "no_blueprint": {},
    }[arguments]

    error = _rejection(settings, context, _handoff_plan(step))
    _same((error.code, error.rule), ("plan_invalid", None), f"the rule for {arguments}")


# ---------------------------------------------------------------------------
# The manual approval floor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("approval_mode,default_mode", [
    (None, "auto"), (None, "timed"), (None, "manual"), ("auto", "manual"), ("timed", "auto"), ("manual", "auto"),
])
def test_normalize_plan_saves_every_hand_off_plan_as_manual_with_a_floor(modules, approval_mode, default_mode):
    settings, context = _context("on", changes={"chat_orchestration_default_approval_mode": default_mode})

    for name, raw in (
        ("hand-off only", _handoff_plan(_handoff_step(_documents_loop(context)))),
        ("mixed", _mixed_plan(_handoff_step(_query_loop(context)))),
    ):
        plan = _normalize(settings, context, raw, approval_mode=approval_mode)
        approval = plan["approval"]
        _same(
            (approval["mode"], approval["state"], plan["status"]), ("manual", "pending", "awaiting_approval"),
            f"the {name} plan's approval",
        )
        _same(approval.get("floor"), FLOOR, f"the {name} plan's floor")
        _same((approval["approved_at"], approval["approved_by"]), (None, None), f"the {name} plan's approver")


def test_only_an_enabled_hand_off_step_sets_the_floor(modules):
    schema = _schema()
    _same(schema.plan_approval_floor({"steps": [{"capability_id": HANDOFF_CAPABILITY}]}), FLOOR, "an enabled step")
    _same(
        schema.plan_approval_floor({"steps": [{"capability_id": HANDOFF_CAPABILITY, "enabled": False}]}), None,
        "a disabled step",
    )
    _same(schema.plan_approval_floor({"steps": [{"capability_id": "compose"}]}), None, "a plan without a hand-off")


def _saved(store, plan, context):
    return store.run_store.create_orchestration_run(
        deepcopy(plan), OWNER, CONVERSATION, turn_index=1,
        turn_context={**deepcopy(TURN_CONTEXT), "workflow_planning": deepcopy(context)}, idempotent=True,
    )


def _claim(store, record, settings, **kwargs):
    return store.revisions.claim_plan_run(
        record["id"], OWNER, CONVERSATION, expected_version=record.get("edit_version"),
        settings=deepcopy(settings), **kwargs,
    )


def _saved_mixed_plan(store):
    settings, context = _context("on", changes={"chat_orchestration_default_approval_mode": "auto"})
    plan = _normalize(settings, context, _mixed_plan(_handoff_step(_documents_loop(context))), approval_mode="auto")
    return settings, _saved(store, plan, context)


def _set_mode(target, mode):
    target["approval"] = {**target["approval"], "mode": mode}


def test_a_saved_hand_off_plan_is_manual_and_runs_when_claimed(store):
    settings, record = _saved_mixed_plan(store)
    _same((record["approval"]["mode"], record["status"]), ("manual", "awaiting_approval"), "the saved run record")
    _same(record["plan"]["approval"].get("floor"), FLOOR, "the saved plan's floor")

    claimed = _claim(store, record, settings)
    _same(claimed["status"], "running", "the claimed run's status")
    _require(claimed["started_at"], "The claimed run must record when it started.")
    _same((claimed["approval"]["state"], claimed["approval"].get("floor")), ("approved", FLOOR), "the claimed approval")


@pytest.mark.parametrize("change", [
    "record_auto", "record_timed", "plan_auto", "plan_timed", "both_auto",
    "record_missing", "plan_missing", "record_not_a_dict",
])
def test_a_saved_hand_off_plan_that_no_longer_reads_manual_cannot_start(store, change):
    settings, record = _saved_mixed_plan(store)
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
        _claim(store, changed, settings)
    saved = store.runs.read_item(record["id"], CONVERSATION)
    _same((caught.value.code, caught.value.status_code), ("approval_floor_required", 409), f"the refusal for {change}")
    _same((saved["status"], saved["started_at"]), ("awaiting_approval", None), f"the saved run after {change}")
    _require("execution_lease" not in saved, f"A refused claim must not take a lease ({change}).")


def test_a_saved_plan_whose_hand_off_step_is_switched_off_is_not_held_back(store):
    settings, record = _saved_mixed_plan(store)
    changed = store.runs.read_item(record["id"], CONVERSATION)
    _set_mode(changed, "auto")
    store.runs.upsert_item(changed)

    claimed = _claim(store, changed, settings, edits={"disabled_step_ids": ["handoff"]})
    handoff = [step for step in claimed["plan"]["steps"] if step["step_id"] == "handoff"]
    _same(claimed["status"], "running", "the claimed run's status")
    _same([step["enabled"] for step in handoff], [False], "the switched-off hand-off step")


@pytest.mark.parametrize("record_mode,plan_mode,refused", [
    ("manual", "manual", False),
    ("auto", "manual", True),
    ("manual", "timed", True),
    ("auto", "auto", True),
])
def test_the_claim_backstop_reads_the_hand_off_floor(modules, record_mode, plan_mode, refused):
    revisions = importlib.import_module("functions_orchestration_plan_revisions")
    plan = {"steps": [{"capability_id": HANDOFF_CAPABILITY}], "approval": {"mode": plan_mode}}
    record = {"approval": {"mode": record_mode}}
    try:
        revisions._require_approval_floor(record, plan)
    except revisions.PlanRevisionError as exc:
        _require(refused, f"A {record_mode}/{plan_mode} hand-off plan was refused.")
        _same(exc.code, "approval_floor_required", "the refusal code")
        return
    _require(not refused, f"A {record_mode}/{plan_mode} hand-off plan was not refused.")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
